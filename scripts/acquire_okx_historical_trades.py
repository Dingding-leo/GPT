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
RETRYABLE = {408, 429, 500, 502, 503, 504}
ALLOWED_HOST_SUFFIXES = (".okx.com", ".okxcdn.com")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    text = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    return text.encode()


def request_bytes(url: str, timeout: float = 30.0) -> tuple[bytes, str, float]:
    request = Request(
        url,
        headers={
            "Accept": "application/json,application/zip,text/csv,*/*",
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    error: Exception | None = None
    for attempt in range(3):
        started = time.monotonic()
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                return response.read(), response.geturl(), time.monotonic() - started
        except HTTPError as exc:
            error = exc
            if exc.code not in RETRYABLE or attempt == 2:
                raise RuntimeError(f"HTTP {exc.code}: {url}") from exc
        except (URLError, TimeoutError) as exc:
            error = exc
            if attempt == 2:
                raise RuntimeError(f"request failed: {url}") from exc
        time.sleep(0.5 * 2**attempt)
    raise RuntimeError(f"request failed: {url}") from error


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


def int_value(value: Any, field: str) -> int:
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


def trade(
    inst_id: str,
    trade_id: Any,
    side: Any,
    price: Any,
    size: Any,
    timestamp: Any,
) -> tuple[str, int, str, Decimal, Decimal, int]:
    parsed_side = str(side).lower()
    parsed_price = Decimal(str(price))
    parsed_size = Decimal(str(size))
    if parsed_side not in {"buy", "sell"} or parsed_price <= 0 or parsed_size <= 0:
        raise ValueError("invalid trade economics")
    return (
        inst_id,
        int_value(trade_id, "trade_id"),
        parsed_side,
        parsed_price,
        parsed_size,
        timestamp_ms(timestamp),
    )


def parse_csv(data: bytes, inst_id: str) -> list[tuple[Any, ...]]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    if reader.fieldnames is None:
        raise ValueError("archive CSV has no header")
    rows = []
    for row in reader:
        rows.append(
            trade(
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


def parse_rest(data: bytes, inst_id: str) -> list[tuple[Any, ...]]:
    payload = json.loads(data.decode())
    if str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise ValueError("invalid REST response")
    rows = []
    for row in payload["data"]:
        if row.get("instId") != inst_id:
            raise ValueError("mixed instrument REST response")
        rows.append(
            trade(
                inst_id,
                row.get("tradeId"),
                row.get("side"),
                row.get("px"),
                row.get("sz"),
                row.get("ts"),
            )
        )
    return rows


def canonical(rows: list[tuple[Any, ...]]) -> list[tuple[Any, ...]]:
    unique: dict[tuple[str, int], tuple[Any, ...]] = {}
    for row in rows:
        key = row[0], row[1]
        if key in unique and unique[key][2:] != row[2:]:
            raise ValueError("conflicting duplicate trade identity")
        unique[key] = row
    return sorted(unique.values(), key=lambda row: (row[5], row[1]))


def features(rows: list[tuple[Any, ...]], reorder: bool = True) -> list[dict[str, Any]]:
    ordered = canonical(rows) if reorder else rows
    grouped: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    for row in ordered:
        grouped[row[5] // HOUR_MS].append(row)
    output = []
    for hour in sorted(grouped):
        trades = grouped[hour]
        total = sum((row[3] * row[4] for row in trades), Decimal())
        signed = sum(
            (
                row[3] * row[4] * (Decimal(1) if row[2] == "buy" else Decimal(-1))
                for row in trades
            ),
            Decimal(),
        )
        output.append(
            {
                "hour_start_ms": hour * HOUR_MS,
                "trade_count": len(trades),
                "flow": format(signed / total, ".18g"),
                "impact_return": format(math.log(float(trades[-1][3] / trades[0][3])), ".18g"),
                "first_trade_id": str(trades[0][1]),
                "last_trade_id": str(trades[-1][1]),
            }
        )
    return output


def strategy_diagnostic(rows: list[tuple[Any, ...]]) -> dict[str, Any]:
    ordered = canonical(rows)
    groups: dict[int, list[tuple[Any, ...]]] = defaultdict(list)
    for row in ordered:
        groups[row[5]].append(row)
    permuted = []
    for row in ordered:
        if row is groups[row[5]][0]:
            permuted.extend(reversed(groups[row[5]]))
    base_features = features(ordered)
    permutation_features = features(permuted)
    naive_base = features(ordered, reorder=False)
    naive_permuted = features(permuted, reorder=False)
    hours = sorted({row[5] // HOUR_MS for row in ordered})
    cutoff = hours[len(hours) // 2]
    prefix = [row for row in ordered if row[5] // HOUR_MS <= cutoff]
    suffix = [row for row in ordered if row[5] // HOUR_MS > cutoff]
    changed = list(suffix)
    last = list(changed[-1])
    last[3] *= Decimal("1.01")
    changed[-1] = tuple(last)
    cutoff_ms = cutoff * HOUR_MS
    original_prefix = [row for row in features(ordered) if row["hour_start_ms"] <= cutoff_ms]
    changed_prefix = [
        row for row in features(prefix + changed) if row["hour_start_ms"] <= cutoff_ms
    ]
    id_order = sorted(ordered, key=lambda row: row[1])
    inversions = sum(left[5] > right[5] for left, right in zip(id_order, id_order[1:]))
    collisions = [len(group) for group in groups.values() if len(group) > 1]
    return {
        "hours": len(base_features),
        "same_timestamp_group_count": len(collisions),
        "maximum_same_timestamp_group_size": max(collisions, default=1),
        "permutation_invariant": base_features == permutation_features,
        "future_suffix_invariant": original_prefix == changed_prefix,
        "trade_id_time_inversion_count": inversions,
        "naive_order_changed_hour_count": sum(
            left != right for left, right in zip(naive_base, naive_permuted)
        ),
        "feature_sha256": sha256(canonical_json(base_features)),
    }


def urls(value: Any) -> list[str]:
    found = []
    if isinstance(value, dict):
        for item in value.values():
            found.extend(urls(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(urls(item))
    elif isinstance(value, str) and value.startswith("https://"):
        stem = value.lower().split("?", 1)[0]
        if stem.endswith((".zip", ".csv", ".gz")):
            found.append(value)
    return sorted(set(found))


def archive_csv(data: bytes) -> tuple[bytes, dict[str, Any]]:
    if not data.startswith(b"PK\x03\x04"):
        return data, {"compression": "none", "member_name": None}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        members = [
            item
            for item in archive.infolist()
            if not item.is_dir() and item.filename.lower().endswith(".csv")
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


def server_time(base_url: str) -> tuple[int, dict[str, Any]]:
    url = f"{base_url}/api/v5/public/time"
    payload, raw, final_url, elapsed = request_json(url)
    rows = payload.get("data")
    if str(payload.get("code")) != "0" or not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("invalid server-time response")
    return int_value(rows[0].get("ts"), "server_time"), {
        "url": url,
        "final_url": final_url,
        "rtt_seconds": elapsed,
        "sha256": sha256(raw),
    }


def rest_page(base_url: str, inst_id: str, name: str, value: int, path: Path) -> list:
    query = urlencode({"instId": inst_id, "type": "1", name: str(value), "limit": "100"})
    raw, _, _ = request_bytes(f"{base_url}/api/v5/market/history-trades?{query}")
    persist(path, raw)
    return parse_rest(raw, inst_id)


def market_checkpoint(base_url: str, inst_id: str, now_ms: int, root: Path) -> dict[str, Any]:
    day0 = datetime.fromtimestamp(now_ms / 1000, UTC).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    archive_url = ""
    attempts = []
    selected_day = ""
    for back in range(4, 11):
        day = day0 - timedelta(days=back)
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
        record = persist(root / f"manifest-{day.date()}.json", raw)
        candidates = urls(payload)
        attempts.append(
            {
                "day": day.date().isoformat(),
                "url": endpoint,
                "final_url": final_url,
                "rtt_seconds": elapsed,
                "response": record,
                "code": str(payload.get("code")),
                "message": str(payload.get("msg", "")),
                "download_url_count": len(candidates),
            }
        )
        if candidates:
            archive_url = candidates[0]
            selected_day = day.date().isoformat()
            break
    if not archive_url:
        return {
            "inst_id": inst_id,
            "status": "blocked_source_unavailable",
            "manifest_attempts": attempts,
        }
    host = (urlparse(archive_url).hostname or "").lower()
    if not host.endswith(ALLOWED_HOST_SUFFIXES):
        raise ValueError(f"archive host not allowed: {host}")
    raw, final_url, elapsed = request_bytes(archive_url, timeout=120.0)
    archive_record = persist(root / "archive.bin", raw)
    csv_data, member = archive_csv(raw)
    csv_record = persist(root / "archive.csv", csv_data)
    archive_rows = canonical(parse_csv(csv_data, inst_id))
    id_order = sorted(archive_rows, key=lambda row: row[1])
    anchor = id_order[len(id_order) // 2][1]
    rest_rows = canonical(
        rest_page(base_url, inst_id, "after", anchor, root / "rest-after.json")
        + rest_page(base_url, inst_id, "before", anchor, root / "rest-before.json")
    )
    archive_by_id = {(row[0], row[1]): row for row in archive_rows}
    overlap = [row for row in rest_rows if (row[0], row[1]) in archive_by_id]
    mismatches = [row for row in overlap if archive_by_id[(row[0], row[1])][2:] != row[2:]]
    replay = canonical(parse_csv(csv_data, inst_id))
    diagnostic = strategy_diagnostic(archive_rows)
    diagnostic["exact_byte_replay_passed"] = features(replay) == features(archive_rows)
    parity = len(overlap) >= 20 and not mismatches
    diagnostic_passed = (
        diagnostic["same_timestamp_group_count"] > 0
        and diagnostic["permutation_invariant"]
        and diagnostic["future_suffix_invariant"]
        and diagnostic["trade_id_time_inversion_count"] == 0
        and diagnostic["exact_byte_replay_passed"]
    )
    return {
        "inst_id": inst_id,
        "status": "checkpoint_passed" if parity and diagnostic_passed else "checkpoint_rejected",
        "selected_day": selected_day,
        "manifest_attempts": attempts,
        "archive": {
            **archive_record,
            "url": archive_url,
            "final_url": final_url,
            "rtt_seconds": elapsed,
            "csv": csv_record,
            "member": member,
            "rows": len(archive_rows),
            "minimum_ts_ms": archive_rows[0][5],
            "maximum_ts_ms": archive_rows[-1][5],
        },
        "rest_overlap": {
            "rest_rows": len(rest_rows),
            "matched_trade_ids": len(overlap),
            "mismatch_count": len(mismatches),
            "parity_passed": parity,
        },
        "strategy_feature_diagnostic": diagnostic,
    }


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    now_ms, time_record = server_time(base_url)
    markets = []
    for inst_id in ("BTC-USDT", "ETH-USDT"):
        try:
            markets.append(market_checkpoint(base_url, inst_id, now_ms, output_dir / inst_id))
        except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
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
        "server_time": time_record,
        "markets": markets,
        "verdict": verdict,
    }
    data = canonical_json(result)
    (output_dir / "result.json").write_bytes(data)
    (output_dir / "result.sha256").write_text(sha256(data) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default="reports/okx/trade-flow-schema-checkpoint")
    parser.add_argument("--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"))
    args = parser.parse_args()
    print(json.dumps(run(Path(args.output_dir), args.base_url.rstrip("/")), indent=2))


if __name__ == "__main__":
    main()
