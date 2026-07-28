from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import time
import zipfile
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
REST_PAGE_SIZE = 100
EXCHANGE_DAY_UTC_OFFSET_HOURS = 8
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
ALLOWED_HOST_SUFFIXES = ("okx.com", "okxcdn.com")

Trade = tuple[str, int, str, Decimal, Decimal, int]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def trusted_okx_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES)


def request_bytes(url: str, timeout: float = 30.0) -> tuple[bytes, str, float]:
    if not trusted_okx_host(url):
        raise ValueError(f"untrusted request host: {url}")
    request = Request(
        url,
        headers={
            "Accept": "application/json,application/zip,text/csv,*/*",
            "User-Agent": "gpt-quant-lab/0.3 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        started = time.monotonic()
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                final_url = response.geturl()
                if not trusted_okx_host(final_url):
                    raise ValueError(f"untrusted final response host: {final_url}")
                return response.read(), final_url, time.monotonic() - started
        except HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_STATUS or attempt == 2:
                raise RuntimeError(f"HTTP {exc.code}: {url}") from exc
        except (TimeoutError, URLError) as exc:
            last_error = exc
            if attempt == 2:
                raise RuntimeError(f"request failed: {url}") from exc
        time.sleep(0.5 * 2**attempt)
    raise RuntimeError(f"request failed: {url}") from last_error


def request_json(url: str) -> tuple[dict[str, Any], bytes, str, float]:
    raw, final_url, elapsed = request_bytes(url)
    payload = json.loads(raw.decode())
    if not isinstance(payload, dict):
        raise ValueError("JSON response is not an object")
    return payload, raw, final_url, elapsed


def persist(path: Path, data: bytes) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path), "bytes": len(data), "sha256": sha256(data)}


def exact_integer(value: Any, field: str) -> int:
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal():
        raise ValueError(f"invalid integer {field}")
    return int(text)


def timestamp_ms(value: Any) -> int:
    text = str(value).strip()
    if text.isascii() and text.isdecimal():
        number = int(text)
        if len(text) <= 10:
            return number * 1000
        if len(text) <= 13:
            return number
        if len(text) <= 16:
            return number // 1000
        return number // 1_000_000
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.astimezone(UTC).timestamp() * 1000)


def pick(row: dict[str, Any], *names: str) -> Any:
    lowered = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value is not None and str(value).strip():
            return value
    raise ValueError(f"missing field {names}")


def normalize_trade(
    inst_id: str,
    trade_id: Any,
    side: Any,
    price: Any,
    size: Any,
    timestamp: Any,
) -> Trade:
    normalized_side = str(side).lower()
    normalized_price = Decimal(str(price))
    normalized_size = Decimal(str(size))
    if normalized_side not in {"buy", "sell"}:
        raise ValueError("invalid taker side")
    if normalized_price <= 0 or normalized_size <= 0:
        raise ValueError("invalid trade economics")
    return (
        inst_id,
        exact_integer(trade_id, "trade_id"),
        normalized_side,
        normalized_price,
        normalized_size,
        timestamp_ms(timestamp),
    )


def parse_archive_csv(data: bytes, inst_id: str) -> list[Trade]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    if reader.fieldnames is None:
        raise ValueError("archive CSV has no header")
    field_by_lower = {field.lower(): field for field in reader.fieldnames}
    instrument_field = next(
        (
            field_by_lower[name]
            for name in ("instrument_name", "instid", "inst_id", "instrument")
            if name in field_by_lower
        ),
        None,
    )
    if instrument_field is None:
        raise ValueError("archive CSV has no instrument identity field")

    rows: list[Trade] = []
    for row in reader:
        observed_instrument = str(row.get(instrument_field, "")).strip()
        if observed_instrument != inst_id:
            raise ValueError(
                f"archive instrument mismatch: expected {inst_id}, observed {observed_instrument}"
            )
        rows.append(
            normalize_trade(
                inst_id,
                pick(row, "trade_id", "tradeid", "id"),
                pick(row, "side"),
                pick(row, "price", "px"),
                pick(row, "size", "sz", "amount"),
                pick(row, "created_time", "timestamp", "ts", "time"),
            )
        )
    if not rows:
        raise ValueError("archive CSV has no trades")
    return rows


def parse_rest(data: bytes, inst_id: str) -> list[Trade]:
    payload = json.loads(data.decode())
    response_rows = payload.get("data")
    if str(payload.get("code")) != "0" or not isinstance(response_rows, list):
        raise ValueError("invalid REST response")
    rows: list[Trade] = []
    for row in response_rows:
        if not isinstance(row, dict) or row.get("instId") != inst_id:
            raise ValueError("mixed or invalid REST response")
        rows.append(
            normalize_trade(
                inst_id,
                row.get("tradeId"),
                row.get("side"),
                row.get("px"),
                row.get("sz"),
                row.get("ts"),
            )
        )
    return rows


def canonicalize(rows: list[Trade]) -> list[Trade]:
    unique: dict[tuple[str, int], Trade] = {}
    for row in rows:
        key = row[0], row[1]
        if key in unique and unique[key][2:] != row[2:]:
            raise ValueError("conflicting duplicate trade identity")
        unique[key] = row
    return sorted(unique.values(), key=lambda row: (row[5], row[1]))


def hourly_features(rows: list[Trade], *, reorder: bool = True) -> list[dict[str, Any]]:
    ordered = canonicalize(rows) if reorder else rows
    grouped: dict[int, list[Trade]] = defaultdict(list)
    for row in ordered:
        grouped[row[5] // HOUR_MS].append(row)

    output: list[dict[str, Any]] = []
    for hour in sorted(grouped):
        hour_rows = grouped[hour]
        total = sum((row[3] * row[4] for row in hour_rows), Decimal())
        if total <= 0:
            raise ValueError("hour has non-positive total quote notional")
        signed = sum(
            (
                row[3] * row[4] * (Decimal(1) if row[2] == "buy" else Decimal(-1))
                for row in hour_rows
            ),
            Decimal(),
        )
        first_price = hour_rows[0][3]
        last_price = hour_rows[-1][3]
        output.append(
            {
                "hour_start_ms": hour * HOUR_MS,
                "trade_count": len(hour_rows),
                "flow": format(signed / total, ".18g"),
                "impact_return": format(math.log(float(last_price / first_price)), ".18g"),
                "first_trade_id": str(hour_rows[0][1]),
                "last_trade_id": str(hour_rows[-1][1]),
            }
        )
    return output


def validate_complete_exchange_day(
    rows: list[Trade],
    *,
    expected_start_ms: int,
) -> dict[str, Any]:
    if expected_start_ms % HOUR_MS:
        raise ValueError("declared archive start is not aligned to an hour")
    ordered = canonicalize(rows)
    expected_end_ms = expected_start_ms + DAY_MS
    if any(not expected_start_ms <= row[5] < expected_end_ms for row in ordered):
        raise ValueError("archive trade falls outside declared exchange day")
    observed_hours = sorted({row[5] // HOUR_MS for row in ordered})
    expected_hours = [expected_start_ms // HOUR_MS + offset for offset in range(24)]
    if observed_hours != expected_hours:
        raise ValueError("archive does not contain all 24 consecutive declared hours")
    return {
        "expected_start_ms": expected_start_ms,
        "expected_end_exclusive_ms": expected_end_ms,
        "hour_count": 24,
        "first_hour_start_ms": observed_hours[0] * HOUR_MS,
        "last_hour_start_ms": observed_hours[-1] * HOUR_MS,
        "minimum_ts_ms": ordered[0][5],
        "maximum_ts_ms": ordered[-1][5],
        "complete_24h_passed": True,
    }


def strategy_diagnostic(rows: list[Trade]) -> dict[str, Any]:
    ordered = canonicalize(rows)
    timestamp_groups: dict[int, list[Trade]] = defaultdict(list)
    for row in ordered:
        timestamp_groups[row[5]].append(row)

    permuted: list[Trade] = []
    emitted: set[int] = set()
    for row in ordered:
        if row[5] not in emitted:
            emitted.add(row[5])
            permuted.extend(reversed(timestamp_groups[row[5]]))

    base_features = hourly_features(ordered)
    permutation_features = hourly_features(permuted)
    naive_base = hourly_features(ordered, reorder=False)
    naive_permuted = hourly_features(permuted, reorder=False)

    hours = sorted({row[5] // HOUR_MS for row in ordered})
    cutoff = hours[len(hours) // 2]
    prefix = [row for row in ordered if row[5] // HOUR_MS <= cutoff]
    suffix = [row for row in ordered if row[5] // HOUR_MS > cutoff]
    changed_suffix = list(suffix)
    changed_last = list(changed_suffix[-1])
    changed_last[3] *= Decimal("1.01")
    changed_suffix[-1] = tuple(changed_last)  # type: ignore[assignment]

    cutoff_ms = cutoff * HOUR_MS
    original_prefix = [
        row for row in hourly_features(ordered) if row["hour_start_ms"] <= cutoff_ms
    ]
    changed_prefix = [
        row
        for row in hourly_features(prefix + changed_suffix)
        if row["hour_start_ms"] <= cutoff_ms
    ]

    trade_id_order = sorted(ordered, key=lambda row: row[1])
    inversions = sum(left[5] > right[5] for left, right in pairwise(trade_id_order))
    collision_sizes = [len(group) for group in timestamp_groups.values() if len(group) > 1]
    naive_changes = sum(
        left != right for left, right in zip(naive_base, naive_permuted, strict=True)
    )
    return {
        "hours": len(base_features),
        "same_timestamp_group_count": len(collision_sizes),
        "maximum_same_timestamp_group_size": max(collision_sizes, default=1),
        "permutation_invariant": base_features == permutation_features,
        "future_suffix_invariant": original_prefix == changed_prefix,
        "trade_id_time_inversion_count": inversions,
        "naive_order_changed_hour_count": naive_changes,
        "feature_sha256": sha256(canonical_json(base_features)),
    }


def find_download_records(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        urls = [
            item
            for item in value.values()
            if isinstance(item, str)
            and item.startswith("https://")
            and item.lower().split("?", 1)[0].endswith((".zip", ".csv", ".gz"))
        ]
        for url in urls:
            found.append({**value, "url": url})
        for item in value.values():
            found.extend(find_download_records(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(find_download_records(item))
    unique: dict[str, dict[str, Any]] = {}
    for record in found:
        unique[str(record["url"])] = record
    return [unique[url] for url in sorted(unique)]


def extract_csv(data: bytes) -> tuple[bytes, dict[str, Any]]:
    if not data.startswith(b"PK\x03\x04"):
        return data, {"compression": "none", "member_name": None}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [
            member
            for member in archive.infolist()
            if not member.is_dir() and member.filename.lower().endswith(".csv")
        ]
        if len(members) != 1:
            raise ValueError("archive must contain exactly one CSV")
        member = members[0]
        csv_data = archive.read(member)
        return csv_data, {
            "compression": "zip",
            "member_name": member.filename,
            "member_size": member.file_size,
            "member_crc": member.CRC,
            "member_sha256": sha256(csv_data),
        }


def fetch_server_time(base_url: str) -> tuple[int, dict[str, Any]]:
    url = f"{base_url}/api/v5/public/time"
    payload, raw, final_url, elapsed = request_json(url)
    rows = payload.get("data")
    if str(payload.get("code")) != "0" or not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("invalid server-time response")
    row = rows[0]
    if not isinstance(row, dict):
        raise ValueError("invalid server-time row")
    return exact_integer(row.get("ts"), "server_time"), {
        "url": url,
        "final_url": final_url,
        "rtt_seconds": elapsed,
        "sha256": sha256(raw),
    }


def fetch_rest_page(
    base_url: str,
    inst_id: str,
    *,
    parameters: dict[str, str],
    path: Path,
) -> list[Trade]:
    query = urlencode(
        {
            "instId": inst_id,
            "type": "1",
            **parameters,
            "limit": str(REST_PAGE_SIZE),
        }
    )
    url = f"{base_url}/api/v5/market/history-trades?{query}"
    raw, final_url, elapsed = request_bytes(url)
    record = persist(path, raw)
    metadata = {
        **record,
        "url": url,
        "final_url": final_url,
        "rtt_seconds": elapsed,
        "parameters": parameters,
    }
    persist(path.with_suffix(".metadata.json"), canonical_json(metadata))
    return parse_rest(raw, inst_id)


def query_archive(
    base_url: str,
    inst_id: str,
    now_ms: int,
    root: Path,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    day0 = datetime.fromtimestamp(now_ms / 1000, UTC).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    attempts: list[dict[str, Any]] = []
    for days_back in range(4, 11):
        requested_day = day0 - timedelta(days=days_back)
        begin = int(requested_day.timestamp() * 1000)
        end = int((requested_day + timedelta(days=1)).timestamp() * 1000) - 1
        query = urlencode(
            {
                "module": "1",
                "instType": "SPOT",
                "instIdList": inst_id,
                "dateAggrType": "daily",
                "begin": str(begin),
                "end": str(end),
            }
        )
        endpoint = f"{base_url}/api/v5/public/market-data-history?{query}"
        try:
            payload, raw, final_url, elapsed = request_json(endpoint)
        except RuntimeError as exc:
            attempts.append({"requested_day": requested_day.date().isoformat(), "error": str(exc)})
            continue

        response = persist(root / f"manifest-{requested_day.date()}.json", raw)
        records = find_download_records(payload)
        accepted: list[dict[str, Any]] = []
        for record in records:
            if str(record.get("instId", inst_id)) != inst_id:
                continue
            try:
                declared_start_ms = exact_integer(record.get("dateTs"), "dateTs")
            except ValueError:
                continue
            expected_start_ms = begin - EXCHANGE_DAY_UTC_OFFSET_HOURS * HOUR_MS
            if declared_start_ms != expected_start_ms:
                continue
            accepted.append(
                {
                    "url": str(record["url"]),
                    "declared_start_ms": declared_start_ms,
                    "requested_begin_ms": begin,
                    "requested_end_ms": end,
                    "requested_day": requested_day.date().isoformat(),
                    "manifest_record": record,
                }
            )

        attempts.append(
            {
                "requested_day": requested_day.date().isoformat(),
                "url": endpoint,
                "final_url": final_url,
                "rtt_seconds": elapsed,
                "response": response,
                "code": str(payload.get("code")),
                "message": str(payload.get("msg", "")),
                "download_record_count": len(records),
                "accepted_record_count": len(accepted),
            }
        )
        if len(accepted) == 1:
            return accepted[0], attempts
        if len(accepted) > 1:
            raise ValueError("manifest returned multiple matching daily archive files")
    return None, attempts


def select_overlap_anchor(
    archive_rows: list[Trade],
) -> tuple[int, int, set[int], set[int]]:
    id_order = sorted(archive_rows, key=lambda row: row[1])
    if len(id_order) < 2 * REST_PAGE_SIZE + 2:
        raise ValueError("archive is too small for two-sided REST overlap")

    indices_by_ts: dict[int, list[int]] = defaultdict(list)
    for index, row in enumerate(id_order):
        indices_by_ts[row[5]].append(index)

    for indices in indices_by_ts.values():
        if len(indices) < 2:
            continue
        candidate_indices = (min(indices) - 1, max(indices) + 1)
        for anchor_index in candidate_indices:
            if anchor_index < REST_PAGE_SIZE:
                continue
            if anchor_index + REST_PAGE_SIZE + 1 >= len(id_order):
                continue
            older = id_order[anchor_index - REST_PAGE_SIZE : anchor_index]
            newer = id_order[anchor_index + 1 : anchor_index + 1 + REST_PAGE_SIZE]
            combined = older + newer
            collision_counts: dict[int, int] = defaultdict(int)
            for row in combined:
                collision_counts[row[5]] += 1
            if max(collision_counts.values(), default=1) < 2:
                continue
            anchor = id_order[anchor_index][1]
            newer_bound = id_order[anchor_index + REST_PAGE_SIZE + 1][1]
            return (
                anchor,
                newer_bound,
                {row[1] for row in older},
                {row[1] for row in newer},
            )
    raise ValueError("could not preselect a two-sided overlap containing an equal-ms collision")


def validate_rest_pages(
    *,
    inst_id: str,
    archive_rows: list[Trade],
    older_rows: list[Trade],
    newer_rows: list[Trade],
    anchor: int,
    newer_bound: int,
    expected_older_ids: set[int],
    expected_newer_ids: set[int],
) -> dict[str, Any]:
    if len(older_rows) != REST_PAGE_SIZE or len(newer_rows) != REST_PAGE_SIZE:
        raise ValueError("REST page did not return exactly 100 rows")

    older_keys = [(row[0], row[1]) for row in older_rows]
    newer_keys = [(row[0], row[1]) for row in newer_rows]
    if len(set(older_keys)) != REST_PAGE_SIZE or len(set(newer_keys)) != REST_PAGE_SIZE:
        raise ValueError("REST page contains duplicate identities")
    if set(older_keys) & set(newer_keys):
        raise ValueError("REST pages contain cross-page duplicate identities")
    if any(row[0] != inst_id for row in older_rows + newer_rows):
        raise ValueError("REST pages contain mixed instruments")
    if any(row[1] >= anchor for row in older_rows):
        raise ValueError("older REST page violates after-cursor direction")
    if any(not anchor < row[1] < newer_bound for row in newer_rows):
        raise ValueError("bounded newer REST page violates cursor direction")
    if {row[1] for row in older_rows} != expected_older_ids:
        raise ValueError("older REST page does not equal the archive-adjacent 100 IDs")
    if {row[1] for row in newer_rows} != expected_newer_ids:
        raise ValueError("newer REST page does not equal the archive-adjacent 100 IDs")

    archive_by_id = {(row[0], row[1]): row for row in archive_rows}
    combined = older_rows + newer_rows
    unmatched = [row for row in combined if (row[0], row[1]) not in archive_by_id]
    mismatches = [
        row
        for row in combined
        if (row[0], row[1]) in archive_by_id
        and archive_by_id[(row[0], row[1])][2:] != row[2:]
    ]
    timestamp_counts: dict[int, int] = defaultdict(int)
    for row in combined:
        timestamp_counts[row[5]] += 1
    equal_ms_groups = [count for count in timestamp_counts.values() if count > 1]

    if unmatched:
        raise ValueError("REST overlap contains IDs absent from the archive")
    if mismatches:
        raise ValueError("REST/archive economic fields differ")
    if not equal_ms_groups:
        raise ValueError("matched 200-row overlap has no equal-millisecond collision")

    return {
        "anchor_trade_id": str(anchor),
        "newer_bound_trade_id": str(newer_bound),
        "older_page_rows": len(older_rows),
        "newer_page_rows": len(newer_rows),
        "cross_page_unique_rows": len(combined),
        "archive_matched_trade_ids": len(combined),
        "economic_field_mismatch_count": 0,
        "older_cursor_direction_passed": True,
        "newer_cursor_direction_passed": True,
        "archive_adjacent_id_sets_passed": True,
        "equal_millisecond_group_count": len(equal_ms_groups),
        "maximum_equal_millisecond_group_size": max(equal_ms_groups),
        "parity_passed": True,
    }


def market_checkpoint(
    base_url: str,
    inst_id: str,
    now_ms: int,
    root: Path,
) -> dict[str, Any]:
    archive_selection, attempts = query_archive(base_url, inst_id, now_ms, root)
    if archive_selection is None:
        return {
            "inst_id": inst_id,
            "status": "blocked_source_unavailable",
            "manifest_attempts": attempts,
        }

    archive_url = archive_selection["url"]
    raw, final_url, elapsed = request_bytes(archive_url, timeout=120.0)
    archive_record = persist(root / "archive.bin", raw)
    csv_data, member_record = extract_csv(raw)
    csv_record = persist(root / "archive.csv", csv_data)
    archive_rows = canonicalize(parse_archive_csv(csv_data, inst_id))
    day_validation = validate_complete_exchange_day(
        archive_rows,
        expected_start_ms=archive_selection["declared_start_ms"],
    )

    id_order = sorted(archive_rows, key=lambda row: row[1])
    inversion_count = sum(left[5] > right[5] for left, right in pairwise(id_order))
    if inversion_count:
        raise ValueError("trade IDs invert exchange event time")

    anchor, newer_bound, expected_older_ids, expected_newer_ids = select_overlap_anchor(
        archive_rows
    )
    older_rows = fetch_rest_page(
        base_url,
        inst_id,
        parameters={"after": str(anchor)},
        path=root / "rest-older.json",
    )
    newer_rows = fetch_rest_page(
        base_url,
        inst_id,
        parameters={"before": str(anchor), "after": str(newer_bound)},
        path=root / "rest-newer-bounded.json",
    )
    rest_validation = validate_rest_pages(
        inst_id=inst_id,
        archive_rows=archive_rows,
        older_rows=older_rows,
        newer_rows=newer_rows,
        anchor=anchor,
        newer_bound=newer_bound,
        expected_older_ids=expected_older_ids,
        expected_newer_ids=expected_newer_ids,
    )

    replay_rows = canonicalize(parse_archive_csv(csv_data, inst_id))
    diagnostic = strategy_diagnostic(archive_rows)
    diagnostic["exact_byte_replay_passed"] = hourly_features(replay_rows) == hourly_features(
        archive_rows
    )
    diagnostic["trade_id_time_inversion_count"] = inversion_count

    diagnostic_passed = all(
        (
            diagnostic["hours"] == 24,
            diagnostic["same_timestamp_group_count"] > 0,
            diagnostic["permutation_invariant"],
            diagnostic["future_suffix_invariant"],
            diagnostic["trade_id_time_inversion_count"] == 0,
            diagnostic["exact_byte_replay_passed"],
        )
    )
    status = (
        "checkpoint_passed"
        if day_validation["complete_24h_passed"]
        and rest_validation["parity_passed"]
        and diagnostic_passed
        else "checkpoint_rejected"
    )
    return {
        "inst_id": inst_id,
        "status": status,
        "manifest_attempts": attempts,
        "archive_selection": archive_selection,
        "archive": {
            **archive_record,
            "url": archive_url,
            "final_url": final_url,
            "rtt_seconds": elapsed,
            "csv": csv_record,
            "member": member_record,
            "rows": len(archive_rows),
            **day_validation,
        },
        "rest_overlap": rest_validation,
        "strategy_feature_diagnostic": diagnostic,
    }


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    now_ms, server_time = fetch_server_time(base_url)
    markets: list[dict[str, Any]] = []
    for inst_id in ("BTC-USDT", "ETH-USDT"):
        try:
            markets.append(
                market_checkpoint(
                    base_url,
                    inst_id,
                    now_ms,
                    output_dir / inst_id,
                )
            )
        except (OSError, RuntimeError, ValueError, zipfile.BadZipFile) as exc:
            markets.append(
                {
                    "inst_id": inst_id,
                    "status": "checkpoint_rejected",
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )

    states = {market["status"] for market in markets}
    if states == {"checkpoint_passed"}:
        verdict = "trade_flow_source_schema_checkpoint_passed"
    elif "checkpoint_rejected" in states:
        verdict = "trade_flow_resilience_family_rejected_pre_performance"
    else:
        verdict = "trade_flow_source_schema_checkpoint_blocked"

    result = {
        "schema_version": "trade-flow-source-schema-checkpoint-v2",
        "architecture_family_id": "okx-spot-causal-trade-flow-resilience-v2",
        "candidate_count": 2,
        "canonical_fee_bps_one_way": 5.0,
        "performance_inspected": False,
        "oos_consumed": False,
        "archive_day_contract": {
            "aggregation": "daily",
            "timezone": "UTC+8",
            "hourly_feature_buckets": "UTC",
        },
        "server_time": server_time,
        "markets": markets,
        "verdict": verdict,
    }
    data = canonical_json(result)
    (output_dir / "result.json").write_bytes(data)
    (output_dir / "result.sha256").write_text(sha256(data) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        default="reports/okx/trade-flow-schema-checkpoint",
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
    )
    args = parser.parse_args()
    result = run(Path(args.output_dir), args.base_url.rstrip("/"))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
