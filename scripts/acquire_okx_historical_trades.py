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
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

HOUR_MS = 3_600_000
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
ALLOWED_ARCHIVE_SUFFIXES = (".okx.com", ".okxcdn.com")
Trade = tuple[str, int, str, Decimal, Decimal, int]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def request_bytes(url: str, timeout: float = 30.0) -> tuple[bytes, str, float]:
    request = Request(
        url,
        headers={
            "Accept": "application/json,application/zip,text/csv,*/*",
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        started = time.monotonic()
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.read(), response.geturl(), time.monotonic() - started
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
    rows = [
        normalize_trade(
            inst_id,
            pick(row, "trade_id", "tradeid", "id"),
            pick(row, "side"),
            pick(row, "price", "px"),
            pick(row, "size", "sz", "amount"),
            pick(row, "created_time", "timestamp", "ts", "time"),
        )
        for row in reader
    ]
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
    original_prefix = [row for row in hourly_features(ordered) if row["hour_start_ms"] <= cutoff_ms]
    changed_prefix = [
        row for row in hourly_features(prefix + changed_suffix) if row["hour_start_ms"] <= cutoff_ms
    ]

    trade_id_order = sorted(ordered, key=lambda row: row[1])
    inversions = sum(
        left[5] > right[5] for left, right in zip(trade_id_order, trade_id_order[1:], strict=True)
    )
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


def find_download_urls(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for item in value.values():
            found.extend(find_download_urls(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(find_download_urls(item))
    elif isinstance(value, str) and value.startswith("https://"):
        stem = value.lower().split("?", 1)[0]
        if stem.endswith((".zip", ".csv", ".gz")):
            found.append(value)
    return sorted(set(found))


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
    cursor_name: str,
    cursor: int,
    path: Path,
) -> list[Trade]:
    query = urlencode(
        {
            "instId": inst_id,
            "type": "1",
            cursor_name: str(cursor),
            "limit": "100",
        }
    )
    url = f"{base_url}/api/v5/market/history-trades?{query}"
    raw, _, _ = request_bytes(url)
    persist(path, raw)
    return parse_rest(raw, inst_id)


def query_archive(
    base_url: str,
    inst_id: str,
    now_ms: int,
    root: Path,
) -> tuple[str, str, list[dict[str, Any]]]:
    day0 = datetime.fromtimestamp(now_ms / 1000, UTC).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    attempts: list[dict[str, Any]] = []
    for days_back in range(4, 11):
        day = day0 - timedelta(days=days_back)
        begin = int(day.timestamp() * 1000)
        end = int((day + timedelta(days=1)).timestamp() * 1000) - 1
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
            attempts.append({"day": day.date().isoformat(), "error": str(exc)})
            continue
        response = persist(root / f"manifest-{day.date()}.json", raw)
        candidates = find_download_urls(payload)
        attempts.append(
            {
                "day": day.date().isoformat(),
                "url": endpoint,
                "final_url": final_url,
                "rtt_seconds": elapsed,
                "response": response,
                "code": str(payload.get("code")),
                "message": str(payload.get("msg", "")),
                "download_url_count": len(candidates),
            }
        )
        if candidates:
            return candidates[0], day.date().isoformat(), attempts
    return "", "", attempts


def market_checkpoint(
    base_url: str,
    inst_id: str,
    now_ms: int,
    root: Path,
) -> dict[str, Any]:
    archive_url, selected_day, attempts = query_archive(
        base_url,
        inst_id,
        now_ms,
        root,
    )
    if not archive_url:
        return {
            "inst_id": inst_id,
            "status": "blocked_source_unavailable",
            "manifest_attempts": attempts,
        }

    host = (urlparse(archive_url).hostname or "").lower()
    if not host.endswith(ALLOWED_ARCHIVE_SUFFIXES):
        raise ValueError(f"archive host not allowed: {host}")

    raw, final_url, elapsed = request_bytes(archive_url, timeout=120.0)
    archive_record = persist(root / "archive.bin", raw)
    csv_data, member_record = extract_csv(raw)
    csv_record = persist(root / "archive.csv", csv_data)
    archive_rows = canonicalize(parse_archive_csv(csv_data, inst_id))

    id_order = sorted(archive_rows, key=lambda row: row[1])
    anchor = id_order[len(id_order) // 2][1]
    rest_rows = canonicalize(
        fetch_rest_page(
            base_url,
            inst_id,
            "after",
            anchor,
            root / "rest-after.json",
        )
        + fetch_rest_page(
            base_url,
            inst_id,
            "before",
            anchor,
            root / "rest-before.json",
        )
    )

    archive_by_id = {(row[0], row[1]): row for row in archive_rows}
    overlap = [row for row in rest_rows if (row[0], row[1]) in archive_by_id]
    mismatches = [row for row in overlap if archive_by_id[(row[0], row[1])][2:] != row[2:]]
    replay_rows = canonicalize(parse_archive_csv(csv_data, inst_id))
    diagnostic = strategy_diagnostic(archive_rows)
    diagnostic["exact_byte_replay_passed"] = hourly_features(replay_rows) == hourly_features(
        archive_rows
    )

    parity_passed = len(overlap) >= 20 and not mismatches
    diagnostic_passed = all(
        (
            diagnostic["same_timestamp_group_count"] > 0,
            diagnostic["permutation_invariant"],
            diagnostic["future_suffix_invariant"],
            diagnostic["trade_id_time_inversion_count"] == 0,
            diagnostic["exact_byte_replay_passed"],
        )
    )
    status = "checkpoint_passed" if parity_passed and diagnostic_passed else "checkpoint_rejected"
    return {
        "inst_id": inst_id,
        "status": status,
        "selected_day": selected_day,
        "manifest_attempts": attempts,
        "archive": {
            **archive_record,
            "url": archive_url,
            "final_url": final_url,
            "rtt_seconds": elapsed,
            "csv": csv_record,
            "member": member_record,
            "rows": len(archive_rows),
            "minimum_ts_ms": archive_rows[0][5],
            "maximum_ts_ms": archive_rows[-1][5],
        },
        "rest_overlap": {
            "rest_rows": len(rest_rows),
            "matched_trade_ids": len(overlap),
            "mismatch_count": len(mismatches),
            "parity_passed": parity_passed,
        },
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
        "schema_version": "trade-flow-source-schema-checkpoint-v1",
        "architecture_family_id": "okx-spot-causal-trade-flow-resilience-v2",
        "candidate_count": 2,
        "canonical_fee_bps_one_way": 5.0,
        "performance_inspected": False,
        "oos_consumed": False,
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
