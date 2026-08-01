from __future__ import annotations

import argparse
import hashlib
import json
import math
import tarfile
import time
from base64 import b64encode
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd

from gpt_quant.okx import write_okx_snapshot
from gpt_quant.okx_1h import fetch_okx_one_hour_candles

FAMILY_ID = "okx-l2-bid-replenishment-resilience-opportunity-diagnostic-1h-v1"
ENDPOINT_PATH = "/api/v5/public/market-data-history"
MODULE = "4"
MARKETS = ("BTC-USDT", "ETH-USDT")
ANCHOR_DATES = (
    "2025-01-07",
    "2025-02-04",
    "2025-03-04",
    "2025-04-01",
    "2025-05-06",
    "2025-06-03",
    "2025-07-01",
    "2025-08-05",
    "2025-09-02",
    "2025-10-07",
    "2025-11-04",
    "2025-12-02",
)
ALLOWED_HOST_SUFFIXES = ("okx.com", "okxcdn.com")
MAX_OBJECT_BYTES = int(1.5 * 1024**3)
MAX_CUMULATIVE_BYTES = 20 * 1024**3
MAX_WORKING_SET_BYTES = 5 * 1024**3
FEE_ONE_WAY = 0.0005
ROUND_TRIP_LABEL_FEE = 0.001
BOUNDARY_STEP_MS = 5 * 60 * 1000
HOUR_MS = 60 * 60 * 1000
DAY_MS = 24 * HOUR_MS
DEPTH_BAND = 0.001
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_SEED = 20_260_801
RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class SourceFeasibilityError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResponseEvidence:
    request_url: str
    final_url: str
    elapsed_seconds: float
    response_bytes: bytes
    payload: dict[str, Any]


class HashingReader:
    def __init__(self, raw: BinaryIO, *, byte_limit: int) -> None:
        self.raw = raw
        self.byte_limit = byte_limit
        self.bytes_read = 0
        self.hasher = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self.raw.read(size)
        self.bytes_read += len(data)
        if self.bytes_read > self.byte_limit:
            raise SourceFeasibilityError("compressed archive exceeds preregistered byte ceiling")
        self.hasher.update(data)
        return data

    def readable(self) -> bool:
        return True

    @property
    def digest(self) -> str:
        return self.hasher.hexdigest()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise SourceFeasibilityError(f"duplicate JSON field: {key}")
        output[key] = value
    return output


def trusted_okx_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and any(
        host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES
    )


def request(url: str, *, accept: str, timeout: float = 90.0) -> BinaryIO:
    if not trusted_okx_url(url):
        raise SourceFeasibilityError(f"untrusted request URL: {url}")
    req = Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)",
        },
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return urlopen(req, timeout=timeout)  # noqa: S310
        except HTTPError as exc:
            last_error = exc
            if exc.code not in RETRYABLE_STATUS or attempt == 2:
                raise SourceFeasibilityError(f"HTTP {exc.code}: {url}") from exc
        except (TimeoutError, URLError) as exc:
            last_error = exc
            if attempt == 2:
                raise SourceFeasibilityError(f"request failed: {url}") from exc
        time.sleep(0.5 * 2**attempt)
    raise SourceFeasibilityError(f"request failed: {url}") from last_error


def fetch_json(url: str, timeout: float = 45.0) -> ResponseEvidence:
    started = time.monotonic()
    with request(url, accept="application/json", timeout=timeout) as response:
        raw = response.read(10_000_001)
        if len(raw) > 10_000_000:
            raise SourceFeasibilityError("metadata response exceeds 10 MB")
        final_url = response.geturl()
    if not trusted_okx_url(final_url):
        raise SourceFeasibilityError(f"untrusted final URL: {final_url}")
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceFeasibilityError("invalid UTF-8 JSON response") from exc
    if not isinstance(parsed, dict):
        raise SourceFeasibilityError("metadata response is not a JSON object")
    return ResponseEvidence(url, final_url, time.monotonic() - started, raw, parsed)


def utc_day_bounds(date_text: str) -> tuple[int, int]:
    start = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=UTC)
    return int(start.timestamp() * 1000), int((start + timedelta(days=1)).timestamp() * 1000)


def positive_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceFeasibilityError(f"invalid numeric field {field}") from exc
    if not math.isfinite(number) or number <= 0:
        raise SourceFeasibilityError(f"non-positive numeric field {field}")
    return number


def nonnegative_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceFeasibilityError(f"invalid numeric field {field}") from exc
    if not math.isfinite(number) or number < 0:
        raise SourceFeasibilityError(f"negative numeric field {field}")
    return number


def string_field(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceFeasibilityError(f"missing string field {field}")
    return value.strip()


def parse_file_records(
    evidence: ResponseEvidence,
    *,
    expected_market: str,
    expected_anchor: str,
) -> list[dict[str, Any]]:
    payload = evidence.payload
    if set(payload) != {"code", "data", "msg"}:
        raise SourceFeasibilityError("unexpected top-level response fields")
    if payload["code"] != "0" or payload["msg"] != "":
        raise SourceFeasibilityError(
            f"provider rejected metadata request: code={payload['code']!r}, msg={payload['msg']!r}"
        )
    data = payload["data"]
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
        raise SourceFeasibilityError("metadata response must contain exactly one result group")
    result = data[0]
    if string_field(result.get("dateAggrType"), "dateAggrType") != "daily":
        raise SourceFeasibilityError("provider did not return daily aggregation")
    details = result.get("details")
    if not isinstance(details, list) or not details:
        raise SourceFeasibilityError("metadata response contains no instrument details")

    records: list[dict[str, Any]] = []
    for detail in details:
        if not isinstance(detail, dict):
            raise SourceFeasibilityError("invalid instrument detail")
        inst_id = string_field(detail.get("instId"), "instId")
        inst_type = string_field(detail.get("instType"), "instType")
        if inst_id != expected_market or inst_type != "SPOT":
            raise SourceFeasibilityError(
                f"instrument mismatch: expected SPOT {expected_market}, got {inst_type} {inst_id}"
            )
        group_details = detail.get("groupDetails")
        if not isinstance(group_details, list) or not group_details:
            raise SourceFeasibilityError("instrument detail contains no downloadable objects")
        for item in group_details:
            if not isinstance(item, dict):
                raise SourceFeasibilityError("invalid file detail")
            url = string_field(item.get("url"), "url")
            if not trusted_okx_url(url):
                raise SourceFeasibilityError(f"untrusted archive URL: {url}")
            size_mb = positive_float(item.get("sizeMB"), "sizeMB")
            records.append(
                {
                    "anchor_date_utc": expected_anchor,
                    "market": expected_market,
                    "inst_type": inst_type,
                    "inst_family": str(detail.get("instFamily", "")),
                    "date_range_start": str(detail.get("dateRangeStart", "")),
                    "date_range_end": str(detail.get("dateRangeEnd", "")),
                    "date_ts": string_field(item.get("dateTs"), "dateTs"),
                    "filename": string_field(item.get("filename"), "filename"),
                    "url": url,
                    "size_mb_decimal": format(size_mb, ".12g"),
                    "declared_compressed_bytes_decimal_mb": int(round(size_mb * 1_000_000)),
                }
            )
    if len(records) != 1:
        raise SourceFeasibilityError(
            f"expected one source object for {expected_market} {expected_anchor}, got {len(records)}"
        )
    return records


def metadata_url(base_url: str, market: str, anchor: str) -> str:
    begin, end_exclusive = utc_day_bounds(anchor)
    query = urlencode(
        {
            "module": MODULE,
            "instType": "SPOT",
            "instIdList": market,
            "dateAggrType": "daily",
            "begin": str(begin),
            "end": str(end_exclusive - 1),
        }
    )
    return f"{base_url.rstrip('/')}{ENDPOINT_PATH}?{query}"


def acquire_metadata(base_url: str, output_dir: Path) -> dict[str, Any]:
    if base_url.rstrip("/") != "https://www.okx.com":
        raise ValueError("base URL must be exactly https://www.okx.com")
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "metadata-responses"
    raw_dir.mkdir(exist_ok=True)
    responses: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for market in MARKETS:
        for anchor in ANCHOR_DATES:
            evidence = fetch_json(metadata_url(base_url, market, anchor))
            raw_path = raw_dir / f"{market}-{anchor}.json"
            raw_path.write_bytes(evidence.response_bytes)
            responses.append(
                {
                    "market": market,
                    "anchor_date_utc": anchor,
                    "request_url": evidence.request_url,
                    "final_url": evidence.final_url,
                    "elapsed_seconds": evidence.elapsed_seconds,
                    "response_path": str(raw_path.relative_to(output_dir)),
                    "response_bytes": len(evidence.response_bytes),
                    "response_sha256": sha256(evidence.response_bytes),
                    "response_base64": b64encode(evidence.response_bytes).decode("ascii"),
                }
            )
            records.extend(
                parse_file_records(
                    evidence,
                    expected_market=market,
                    expected_anchor=anchor,
                )
            )
    urls = [record["url"] for record in records]
    if len(set(urls)) != len(urls):
        raise SourceFeasibilityError("duplicate archive URL in frozen cohort")
    declared_total = sum(record["declared_compressed_bytes_decimal_mb"] for record in records)
    largest = max(record["declared_compressed_bytes_decimal_mb"] for record in records)
    if largest > MAX_OBJECT_BYTES:
        raise SourceFeasibilityError("declared archive exceeds 1.5 GiB object ceiling")
    if declared_total > MAX_CUMULATIVE_BYTES:
        raise SourceFeasibilityError("declared cohort exceeds 20 GiB cumulative ceiling")
    manifest = {
        "family_id": FAMILY_ID,
        "provider": "OKX",
        "endpoint": f"https://www.okx.com{ENDPOINT_PATH}",
        "module": MODULE,
        "module_description": "400-level order-book history",
        "markets": list(MARKETS),
        "anchor_dates_utc": list(ANCHOR_DATES),
        "metadata_responses": responses,
        "source_objects": sorted(records, key=lambda item: (item["market"], item["anchor_date_utc"])),
        "source_object_count": len(records),
        "declared_compressed_bytes": declared_total,
        "largest_object_bytes": largest,
        "per_object_ceiling_bytes": MAX_OBJECT_BYTES,
        "cumulative_ceiling_bytes": MAX_CUMULATIVE_BYTES,
        "working_set_ceiling_bytes": MAX_WORKING_SET_BYTES,
        "byte_gate_passed": True,
        "economic_values_read": False,
    }
    manifest_bytes = canonical_json(manifest)
    (output_dir / "source-manifest.json").write_bytes(manifest_bytes)
    return {"source_manifest_sha256": sha256(manifest_bytes), **manifest}


def parse_level(level: Any, *, side: str) -> tuple[float, float]:
    if not isinstance(level, list) or len(level) != 3:
        raise SourceFeasibilityError(f"{side} level must have exactly three fields")
    price = positive_float(level[0], f"{side}.price")
    size = nonnegative_float(level[1], f"{side}.size")
    count_text = str(level[2])
    if not count_text.isascii() or not count_text.isdecimal():
        raise SourceFeasibilityError(f"invalid {side} order count")
    count = int(count_text)
    if (size == 0.0) != (count == 0):
        raise SourceFeasibilityError(f"inconsistent {side} zero size/order count")
    return price, size


def apply_levels(book: dict[float, float], levels: Any, *, side: str) -> None:
    if not isinstance(levels, list):
        raise SourceFeasibilityError(f"{side} levels must be a list")
    seen: set[float] = set()
    for raw_level in levels:
        price, size = parse_level(raw_level, side=side)
        if price in seen:
            raise SourceFeasibilityError(f"duplicate {side} price in one message")
        seen.add(price)
        if size == 0.0:
            book.pop(price, None)
        else:
            book[price] = size


def boundary_state(bids: dict[float, float], asks: dict[float, float]) -> dict[str, Any] | None:
    if len(bids) < 10 or len(asks) < 10:
        return None
    best_bid = max(bids)
    best_ask = min(asks)
    if not best_bid < best_ask:
        raise SourceFeasibilityError("crossed or locked reconstructed book")
    mid = (best_bid + best_ask) / 2.0
    bid_floor = mid * (1.0 - DEPTH_BAND)
    ask_ceiling = mid * (1.0 + DEPTH_BAND)
    bid_depth = sum(price * size for price, size in bids.items() if price >= bid_floor)
    ask_depth = sum(price * size for price, size in asks.items() if price <= ask_ceiling)
    if not all(math.isfinite(value) and value > 0 for value in (mid, bid_depth, ask_depth)):
        return None
    return {
        "mid": mid,
        "bid_depth_10bp": bid_depth,
        "ask_depth_10bp": ask_depth,
        "bid_levels": len(bids),
        "ask_levels": len(asks),
    }


def hourly_states(
    boundaries: list[dict[str, Any] | None], *, market: str, anchor: str, day_start_ms: int
) -> list[dict[str, Any]]:
    if len(boundaries) != 289:
        raise SourceFeasibilityError(f"expected 289 boundaries, got {len(boundaries)}")
    output: list[dict[str, Any]] = []
    for hour in range(24):
        base = hour * 12
        window = boundaries[base : base + 13]
        record: dict[str, Any] = {
            "market": market,
            "anchor_date_utc": anchor,
            "hour_start_ms": day_start_ms + hour * HOUR_MS,
            "valid": False,
            "invalid_reason": None,
            "state": None,
        }
        if any(item is None for item in window):
            record["invalid_reason"] = "missing_causal_boundary_state"
            output.append(record)
            continue
        states = [item for item in window if item is not None]
        five_minute_returns = [
            math.log(states[index + 1]["mid"] / states[index]["mid"]) for index in range(6)
        ]
        selected = min(range(6), key=lambda index: (five_minute_returns[index], index))
        selected_return = five_minute_returns[selected]
        if selected_return >= 0:
            state = 0.0
            recovery = 0.0
            replenishment = 0.0
            shock = 0.0
        else:
            pre = states[selected]
            trough = states[selected + 1]
            end = states[12]
            shock = math.log(pre["mid"] / trough["mid"])
            if not math.isfinite(shock) or shock <= 0:
                raise SourceFeasibilityError("invalid positive shock magnitude")
            recovery = math.log(end["mid"] / trough["mid"]) / shock
            replenishment = math.log(end["bid_depth_10bp"] / trough["bid_depth_10bp"]) - math.log(
                end["ask_depth_10bp"] / trough["ask_depth_10bp"]
            )
            state = recovery + replenishment
        if not all(math.isfinite(value) for value in (state, shock, recovery, replenishment)):
            raise SourceFeasibilityError("non-finite hourly state")
        record.update(
            {
                "valid": True,
                "state": state,
                "selected_bin": selected,
                "selected_return": selected_return,
                "shock_magnitude": shock,
                "price_recovery": recovery,
                "depth_replenishment": replenishment,
            }
        )
        output.append(record)
    return output


def process_archive(manifest_path: Path, market: str, anchor: str, output_dir: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("family_id") != FAMILY_ID or manifest.get("byte_gate_passed") is not True:
        raise SourceFeasibilityError("invalid or unapproved source manifest")
    matches = [
        item
        for item in manifest.get("source_objects", [])
        if item.get("market") == market and item.get("anchor_date_utc") == anchor
    ]
    if len(matches) != 1:
        raise SourceFeasibilityError("source manifest does not identify exactly one archive")
    source = matches[0]
    url = source["url"]
    day_start_ms, day_end_ms = utc_day_bounds(anchor)
    boundary_times = [day_start_ms + index * BOUNDARY_STEP_MS for index in range(289)]
    boundaries: list[dict[str, Any] | None] = []
    boundary_index = 0
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    snapshot_seen = False
    first_ts: int | None = None
    previous_ts: int | None = None
    last_ts: int | None = None
    row_count = 0
    snapshot_count = 0
    update_count = 0
    member_count = 0
    member_name: str | None = None
    member_bytes = 0
    member_hasher = hashlib.sha256()
    started = time.monotonic()

    with request(url, accept="application/gzip,application/octet-stream,*/*", timeout=120) as response:
        final_url = response.geturl()
        if not trusted_okx_url(final_url):
            raise SourceFeasibilityError(f"untrusted archive final URL: {final_url}")
        reader = HashingReader(response, byte_limit=MAX_OBJECT_BYTES)
        with tarfile.open(fileobj=reader, mode="r|gz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                member_count += 1
                if member_count > 1:
                    raise SourceFeasibilityError("archive contains more than one regular file")
                member_name = member.name
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise SourceFeasibilityError("archive member cannot be read")
                for raw_line in extracted:
                    member_bytes += len(raw_line)
                    member_hasher.update(raw_line)
                    if len(raw_line) > 1_000_000:
                        raise SourceFeasibilityError("order-book message exceeds 1 MB")
                    try:
                        message = json.loads(
                            raw_line.decode("utf-8"), object_pairs_hook=reject_duplicate_keys
                        )
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        raise SourceFeasibilityError("invalid order-book JSON line") from exc
                    if not isinstance(message, dict) or set(message) != {
                        "instId",
                        "action",
                        "ts",
                        "asks",
                        "bids",
                    }:
                        raise SourceFeasibilityError("order-book message schema drift")
                    if message["instId"] != market:
                        raise SourceFeasibilityError("archive contains wrong instrument")
                    ts_text = str(message["ts"])
                    if not ts_text.isascii() or not ts_text.isdecimal():
                        raise SourceFeasibilityError("invalid order-book timestamp")
                    ts = int(ts_text)
                    if not day_start_ms <= ts < day_end_ms:
                        raise SourceFeasibilityError("order-book timestamp outside anchor day")
                    if previous_ts is not None and ts - previous_ts != 10:
                        raise SourceFeasibilityError(
                            f"provider 10 ms sequence continuity gap: {previous_ts} -> {ts}"
                        )
                    if first_ts is None:
                        first_ts = ts
                    previous_ts = ts
                    last_ts = ts
                    while boundary_index < len(boundary_times) and boundary_times[boundary_index] < ts:
                        boundaries.append(boundary_state(bids, asks) if snapshot_seen else None)
                        boundary_index += 1
                    action = message["action"]
                    if action == "snapshot":
                        bids.clear()
                        asks.clear()
                        snapshot_count += 1
                        snapshot_seen = True
                    elif action == "update":
                        if not snapshot_seen:
                            raise SourceFeasibilityError("incremental update precedes initial snapshot")
                        update_count += 1
                    else:
                        raise SourceFeasibilityError(f"unsupported order-book action: {action!r}")
                    apply_levels(asks, message["asks"], side="ask")
                    apply_levels(bids, message["bids"], side="bid")
                    while boundary_index < len(boundary_times) and boundary_times[boundary_index] == ts:
                        boundaries.append(boundary_state(bids, asks))
                        boundary_index += 1
                    row_count += 1
        while reader.read(1 << 20):
            pass
        compressed_bytes = reader.bytes_read
        compressed_sha256 = reader.digest

    if member_count != 1 or member_name is None:
        raise SourceFeasibilityError("archive contains no regular data member")
    if first_ts is None or last_ts is None:
        raise SourceFeasibilityError("archive contains no order-book messages")
    while boundary_index < len(boundary_times):
        boundaries.append(boundary_state(bids, asks) if snapshot_seen else None)
        boundary_index += 1
    expected_rows = (last_ts - first_ts) // 10 + 1
    if row_count != expected_rows:
        raise SourceFeasibilityError("timestamp sequence is not unique and contiguous")
    if first_ts - day_start_ms >= 10 or day_end_ms - last_ts > 10:
        raise SourceFeasibilityError("archive does not cover the complete UTC day at 10 ms cadence")
    if snapshot_count < 1 or update_count < 1:
        raise SourceFeasibilityError("archive lacks snapshot/update semantics")

    states = hourly_states(boundaries, market=market, anchor=anchor, day_start_ms=day_start_ms)
    valid_states = sum(bool(item["valid"]) for item in states)
    invalid_after_first = [item for item in states[1:] if not item["valid"]]
    if invalid_after_first:
        raise SourceFeasibilityError("missing five-minute boundary after the day-opening causal edge")
    result = {
        "family_id": FAMILY_ID,
        "market": market,
        "anchor_date_utc": anchor,
        "source_url": url,
        "final_url": final_url,
        "declared_size_mb": source["size_mb_decimal"],
        "compressed_bytes": compressed_bytes,
        "compressed_sha256": compressed_sha256,
        "member_name": member_name,
        "member_bytes": member_bytes,
        "member_sha256": member_hasher.hexdigest(),
        "message_count": row_count,
        "snapshot_count": snapshot_count,
        "update_count": update_count,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "sequence_identity": "unique strictly increasing 10 ms generation timestamp",
        "sequence_continuity_passed": True,
        "source_day_complete": True,
        "boundary_count": len(boundaries),
        "valid_hour_count": valid_states,
        "invalid_hour_count": 24 - valid_states,
        "first_hour_missing_reason": states[0]["invalid_reason"],
        "processing_seconds": time.monotonic() - started,
        "hourly_states": states,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{market}-{anchor}.json"
    output_path.write_bytes(canonical_json(result))
    return result


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=float)
    index = 0
    while index < len(values):
        end = index + 1
        while end < len(values) and values[order[end]] == values[order[index]]:
            end += 1
        ranks[order[index:end]] = (index + end - 1) / 2.0 + 1.0
        index = end
    return ranks


def correlation(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])


def spearman(left: np.ndarray, right: np.ndarray) -> float:
    return correlation(average_ranks(left), average_ranks(right))


def standardized_slope(state: np.ndarray, target: np.ndarray) -> float:
    standard_deviation = float(np.std(state, ddof=0))
    if standard_deviation == 0:
        return float("nan")
    normalized = (state - float(np.mean(state))) / standard_deviation
    return float(np.mean((normalized - np.mean(normalized)) * (target - np.mean(target))))


def high_minus_low(state: np.ndarray, target: np.ndarray) -> tuple[float, int, int, float]:
    median = float(np.median(state))
    high = state > median
    low = ~high
    if not high.any() or not low.any():
        return float("nan"), int(high.sum()), int(low.sum()), median
    return float(np.mean(target[high]) - np.mean(target[low])), int(high.sum()), int(low.sum()), median


def bucket_analysis(state: np.ndarray, target: np.ndarray) -> dict[str, Any]:
    order = np.argsort(state, kind="mergesort")
    bucket = np.empty(len(state), dtype=int)
    for rank, position in enumerate(order):
        bucket[position] = min(4, rank * 5 // len(state))
    means = [float(np.mean(target[bucket == index])) for index in range(5)]
    favourable = sum(right > left for left, right in zip(means, means[1:], strict=True))
    return {
        "means": means,
        "favourable_adjacent_changes": favourable,
        "bucket_index_correlation": correlation(np.arange(5, dtype=float), np.asarray(means)),
        "counts": [int((bucket == index).sum()) for index in range(5)],
    }


def metric_vector(frame: pd.DataFrame) -> dict[str, float]:
    state = frame["state"].to_numpy(dtype=float)
    net = frame["net_24h"].to_numpy(dtype=float)
    adverse = frame["adverse_24h"].to_numpy(dtype=float)
    return {
        "net_rho": spearman(state, net),
        "adverse_rho": spearman(state, adverse),
        "net_slope": standardized_slope(state, net),
        "adverse_slope": standardized_slope(state, adverse),
    }


def bootstrap_intervals(frame: pd.DataFrame, day_order: list[str]) -> dict[str, list[float]]:
    grouped = {day: frame.loc[frame["anchor_date_utc"] == day] for day in day_order}
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    draws: dict[str, list[float]] = {key: [] for key in metric_vector(frame)}
    for _ in range(BOOTSTRAP_DRAWS):
        sampled = rng.integers(0, len(day_order), size=len(day_order))
        resampled = pd.concat([grouped[day_order[index]] for index in sampled], ignore_index=True)
        metrics = metric_vector(resampled)
        for key, value in metrics.items():
            if math.isfinite(value):
                draws[key].append(value)
    return {
        key: [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]
        for key, values in draws.items()
    }


def day_effects(frame: pd.DataFrame, target: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for day in ANCHOR_DATES:
        subset = frame.loc[frame["anchor_date_utc"] == day]
        effect, high_count, low_count, median = high_minus_low(
            subset["state"].to_numpy(dtype=float), subset[target].to_numpy(dtype=float)
        )
        output.append(
            {
                "anchor_date_utc": day,
                "effect": effect,
                "favourable": bool(effect > 0),
                "high_count": high_count,
                "low_count": low_count,
                "state_median": median,
            }
        )
    return output


def analyze_market(frame: pd.DataFrame) -> dict[str, Any]:
    state = frame["state"].to_numpy(dtype=float)
    net = frame["net_24h"].to_numpy(dtype=float)
    adverse = frame["adverse_24h"].to_numpy(dtype=float)
    net_effect, high_count, low_count, median = high_minus_low(state, net)
    adverse_effect, _, _, _ = high_minus_low(state, adverse)
    metrics = metric_vector(frame)
    intervals = bootstrap_intervals(frame, list(ANCHOR_DATES))
    net_days = day_effects(frame, "net_24h")
    adverse_days = day_effects(frame, "adverse_24h")
    return {
        "observations": len(frame),
        "complete_anchor_days": int(frame["anchor_date_utc"].nunique()),
        "state": {
            "minimum": float(np.min(state)),
            "maximum": float(np.max(state)),
            "median": median,
            "iqr": float(np.quantile(state, 0.75) - np.quantile(state, 0.25)),
            "zero_count": int((state == 0).sum()),
            "high_count": high_count,
            "low_count": low_count,
        },
        "metrics": metrics,
        "confidence_intervals": intervals,
        "median_split": {
            "net_high_minus_low": net_effect,
            "adverse_high_minus_low": adverse_effect,
        },
        "buckets": {
            "net": bucket_analysis(state, net),
            "adverse": bucket_analysis(state, adverse),
        },
        "anchor_day_effects": {"net": net_days, "adverse": adverse_days},
        "positive_anchor_days": {
            "net": sum(item["favourable"] for item in net_days),
            "adverse": sum(item["favourable"] for item in adverse_days),
        },
    }


def acceptance(market_result: dict[str, Any]) -> dict[str, bool]:
    state = market_result["state"]
    metrics = market_result["metrics"]
    intervals = market_result["confidence_intervals"]
    median_split = market_result["median_split"]
    buckets = market_result["buckets"]
    positive_days = market_result["positive_anchor_days"]
    return {
        "support": market_result["observations"] >= 264
        and market_result["complete_anchor_days"] >= 11,
        "state_support": state["iqr"] > 0 and state["high_count"] >= 120 and state["low_count"] >= 120,
        "positive_point_metrics": all(value > 0 for value in metrics.values()),
        "positive_lower_bounds": all(intervals[key][0] > 0 for key in metrics),
        "positive_median_split": median_split["net_high_minus_low"] > 0
        and median_split["adverse_high_minus_low"] > 0,
        "anchor_day_breadth": positive_days["net"] >= 8 and positive_days["adverse"] >= 8,
        "ordered_buckets": all(
            buckets[target]["favourable_adjacent_changes"] >= 3
            and buckets[target]["bucket_index_correlation"] >= 0.80
            for target in ("net", "adverse")
        ),
    }


def load_day_results(days_root: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for market in MARKETS:
        for anchor in ANCHOR_DATES:
            matches = list(days_root.rglob(f"{market}-{anchor}.json"))
            if len(matches) != 1:
                raise SourceFeasibilityError(
                    f"expected one processed day for {market} {anchor}, got {len(matches)}"
                )
            result = json.loads(matches[0].read_text(encoding="utf-8"))
            if result.get("family_id") != FAMILY_ID:
                raise SourceFeasibilityError("processed day family mismatch")
            results.append(result)
    return results


def label_rows(
    states: Iterable[dict[str, Any]], candles: pd.DataFrame, *, delay_hours: int
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in states:
        if not record["valid"]:
            continue
        hour = pd.Timestamp(record["hour_start_ms"], unit="ms", tz="UTC")
        entry = hour + pd.Timedelta(hours=1 + delay_hours)
        exit_time = entry + pd.Timedelta(hours=24)
        path_end = entry + pd.Timedelta(hours=23)
        if entry not in candles.index or exit_time not in candles.index:
            raise SourceFeasibilityError("candle source does not cover executable label endpoints")
        path = candles.loc[entry:path_end]
        if len(path) != 24:
            raise SourceFeasibilityError("candle source does not cover all adverse-excursion bars")
        entry_open = float(candles.at[entry, "open"])
        exit_open = float(candles.at[exit_time, "open"])
        gross = math.log(exit_open / entry_open)
        adverse = float(np.min(np.log(path["low"].to_numpy(dtype=float) / entry_open)))
        output.append(
            {
                **record,
                "entry_open_utc": entry.isoformat(),
                "exit_open_utc": exit_time.isoformat(),
                "gross_24h": gross,
                "net_24h": gross - ROUND_TRIP_LABEL_FEE,
                "adverse_24h": adverse,
            }
        )
    return output


def common_index_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    left = frames[MARKETS[0]][
        ["anchor_date_utc", "hour_start_ms", "state", "net_24h", "adverse_24h"]
    ].rename(columns={"state": "state_left", "net_24h": "net_left", "adverse_24h": "adverse_left"})
    right = frames[MARKETS[1]][
        ["anchor_date_utc", "hour_start_ms", "state", "net_24h", "adverse_24h"]
    ].rename(columns={"state": "state_right", "net_24h": "net_right", "adverse_24h": "adverse_right"})
    merged = left.merge(right, on=["anchor_date_utc", "hour_start_ms"], validate="one_to_one")
    for side in ("left", "right"):
        values = merged[f"state_{side}"].to_numpy(dtype=float)
        deviation = float(np.std(values, ddof=0))
        if deviation == 0:
            raise SourceFeasibilityError("common-index market state has zero standard deviation")
        merged[f"state_z_{side}"] = (values - float(np.mean(values))) / deviation
    return pd.DataFrame(
        {
            "anchor_date_utc": merged["anchor_date_utc"],
            "hour_start_ms": merged["hour_start_ms"],
            "state": (merged["state_z_left"] + merged["state_z_right"]) / 2.0,
            "net_24h": (merged["net_left"] + merged["net_right"]) / 2.0,
            "adverse_24h": (merged["adverse_left"] + merged["adverse_right"]) / 2.0,
        }
    )


def aggregate(metadata_path: Path, days_root: Path, output_dir: Path) -> dict[str, Any]:
    metadata_bytes = metadata_path.read_bytes()
    metadata = json.loads(metadata_bytes)
    if metadata.get("family_id") != FAMILY_ID or metadata.get("byte_gate_passed") is not True:
        raise SourceFeasibilityError("invalid frozen metadata manifest")
    day_results = load_day_results(days_root)
    source_objects = []
    for result in day_results:
        source_objects.append(
            {
                key: result[key]
                for key in (
                    "market",
                    "anchor_date_utc",
                    "source_url",
                    "final_url",
                    "declared_size_mb",
                    "compressed_bytes",
                    "compressed_sha256",
                    "member_name",
                    "member_bytes",
                    "member_sha256",
                    "message_count",
                    "snapshot_count",
                    "update_count",
                    "first_ts",
                    "last_ts",
                    "sequence_identity",
                    "sequence_continuity_passed",
                    "source_day_complete",
                    "boundary_count",
                    "valid_hour_count",
                    "invalid_hour_count",
                    "processing_seconds",
                )
            }
        )
    exact_total = sum(item["compressed_bytes"] for item in source_objects)
    largest = max(item["compressed_bytes"] for item in source_objects)
    if exact_total > MAX_CUMULATIVE_BYTES or largest > MAX_OBJECT_BYTES:
        raise SourceFeasibilityError("observed archive bytes breach frozen ceilings")

    output_dir.mkdir(parents=True, exist_ok=True)
    candle_sources: dict[str, Any] = {}
    primary_frames: dict[str, pd.DataFrame] = {}
    delayed_frames: dict[str, pd.DataFrame] = {}
    primary_results: dict[str, Any] = {}
    delayed_results: dict[str, Any] = {}
    for market in MARKETS:
        candle_snapshot = fetch_okx_one_hour_candles(
            inst_id=market,
            start="2025-01-07T00:00:00Z",
            end="2025-12-04T01:00:00Z",
            base_url="https://www.okx.com",
            timeout=30.0,
        )
        candle_dir = output_dir / "candle-source" / market
        written = write_okx_snapshot(candle_snapshot, candle_dir)
        candle_sources[market] = {
            "metadata": candle_snapshot.metadata,
            "files": {
                name: {
                    "path": str(path.relative_to(output_dir)),
                    "bytes": path.stat().st_size,
                    "sha256": sha256(path.read_bytes()),
                }
                for name, path in written.items()
            },
        }
        states = [
            state
            for result in day_results
            if result["market"] == market
            for state in result["hourly_states"]
        ]
        primary = pd.DataFrame(label_rows(states, candle_snapshot.candles, delay_hours=0))
        delayed = pd.DataFrame(label_rows(states, candle_snapshot.candles, delay_hours=1))
        primary_frames[market] = primary
        delayed_frames[market] = delayed
        primary_results[market] = analyze_market(primary)
        delayed_results[market] = analyze_market(delayed)

    common_primary_frame = common_index_frame(primary_frames)
    common_delayed_frame = common_index_frame(delayed_frames)
    common_primary_result = analyze_market(common_primary_frame)
    common_delayed_result = analyze_market(common_delayed_frame)

    gates: dict[str, Any] = {}
    for market in MARKETS:
        primary_gates = acceptance(primary_results[market])
        delayed_metrics = delayed_results[market]["metrics"]
        delayed_intervals = delayed_results[market]["confidence_intervals"]
        delay_gate = all(value > 0 for value in delayed_metrics.values()) and all(
            delayed_intervals[key][0] > 0 for key in delayed_metrics
        )
        gates[market] = {**primary_gates, "one_hour_delay": delay_gate}
        gates[market]["passed_all"] = all(gates[market].values())

    accepted = all(gates[market]["passed_all"] for market in MARKETS)
    verdict = (
        "accept_okx_l2_bid_replenishment_resilience_information_premise"
        if accepted
        else "reject_okx_l2_bid_replenishment_resilience_information_premise"
    )
    source_manifest = {
        "family_id": FAMILY_ID,
        "metadata_manifest_sha256": sha256(metadata_bytes),
        "metadata": metadata,
        "processed_source_objects": source_objects,
        "exact_compressed_bytes": exact_total,
        "largest_exact_compressed_object_bytes": largest,
        "candle_sources": candle_sources,
    }
    source_manifest_bytes = canonical_json(source_manifest)
    (output_dir / "source-manifest.json").write_bytes(source_manifest_bytes)

    for market in MARKETS:
        primary_frames[market].to_csv(output_dir / f"{market}-primary-labels.csv", index=False)
        delayed_frames[market].to_csv(output_dir / f"{market}-delayed-labels.csv", index=False)

    evidence = {
        "family_id": FAMILY_ID,
        "classification": "training-only information diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "markets": list(MARKETS),
        "timeframe": "1H",
        "fee_one_way": FEE_ONE_WAY,
        "round_trip_label_fee": ROUND_TRIP_LABEL_FEE,
        "new_oos_consumed": False,
        "bootstrap": {
            "draws": BOOTSTRAP_DRAWS,
            "seed": BOOTSTRAP_SEED,
            "unit": "paired complete 24H anchor-day blocks",
        },
        "source_manifest_sha256": sha256(source_manifest_bytes),
        "source": {
            "object_count": len(source_objects),
            "exact_compressed_bytes": exact_total,
            "largest_object_bytes": largest,
            "messages": sum(item["message_count"] for item in source_objects),
            "source_days_complete": sum(item["source_day_complete"] for item in source_objects),
        },
        "primary": primary_results,
        "one_hour_delay": delayed_results,
        "paired_common_anchor_index": {
            "construction": (
                "row-wise mean of independently full-sample-standardized market states and "
                "row-wise mean of market targets; supplementary only"
            ),
            "primary": common_primary_result,
            "one_hour_delay": common_delayed_result,
        },
        "gates": gates,
        "accepted": accepted,
        "verdict": verdict,
        "performance": {
            "training_return": None,
            "training_sharpe": None,
            "oos_return": None,
            "oos_sharpe": None,
            "full_return": None,
            "full_sharpe": None,
            "benchmark_comparison": None,
            "maximum_drawdown": None,
            "turnover": None,
            "edge_per_turnover": None,
            "reason": "candidate count is zero; independent 24H labels are not an equity curve",
        },
    }
    evidence_bytes = canonical_json(evidence)
    (output_dir / "evidence.json").write_bytes(evidence_bytes)

    lines = [
        "# OKX L2 bid-replenishment resilience diagnostic",
        "",
        "```text",
        f"family              {FAMILY_ID}",
        "classification      training-only information diagnostic",
        "candidate count     0",
        "diagnostic count    1",
        "markets             BTC-USDT and ETH-USDT independently",
        "bar                 causal completed UTC 1H",
        "fee                 exactly 5 bps one way; 10 bps per independent 24H label",
        f"verdict             {verdict}",
        "```",
        "",
        "## Market results",
        "",
    ]
    for market in MARKETS:
        primary = primary_results[market]
        delayed = delayed_results[market]
        lines.extend(
            [
                f"### {market}",
                "",
                f"- Valid decisions: {primary['observations']}/288; complete source days: {primary['complete_anchor_days']}/12",
                f"- Net rho: {primary['metrics']['net_rho']:.6f} {primary['confidence_intervals']['net_rho']}",
                f"- Adverse rho: {primary['metrics']['adverse_rho']:.6f} {primary['confidence_intervals']['adverse_rho']}",
                f"- Net slope/state SD: {primary['metrics']['net_slope']:.8f} {primary['confidence_intervals']['net_slope']}",
                f"- Adverse slope/state SD: {primary['metrics']['adverse_slope']:.8f} {primary['confidence_intervals']['adverse_slope']}",
                f"- Median-split net/adverse: {primary['median_split']['net_high_minus_low']:.8f} / {primary['median_split']['adverse_high_minus_low']:.8f}",
                f"- Positive anchor days net/adverse: {primary['positive_anchor_days']['net']}/12 / {primary['positive_anchor_days']['adverse']}/12",
                f"- Delayed net/adverse rho: {delayed['metrics']['net_rho']:.6f} / {delayed['metrics']['adverse_rho']:.6f}",
                f"- Gates: {gates[market]}",
                "",
            ]
        )
    lines.extend(
        [
            "## Paired common-anchor index (supplementary)",
            "",
            f"- Net/adverse rho: {common_primary_result['metrics']['net_rho']:.6f} / {common_primary_result['metrics']['adverse_rho']:.6f}",
            f"- Net/adverse slope per state SD: {common_primary_result['metrics']['net_slope']:.8f} / {common_primary_result['metrics']['adverse_slope']:.8f}",
            "- This aggregate cannot rescue a failed market-level gate.",
            "",
            "## Executable performance",
            "",
            "Training/OOS/full return, Sharpe, benchmark comparison, maximum drawdown, executable turnover and edge per turnover were not computed because the experiment contains zero executable candidates.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    metadata_parser = subparsers.add_parser("metadata")
    metadata_parser.add_argument("--base-url", default="https://www.okx.com")
    metadata_parser.add_argument("--output-dir", type=Path, required=True)
    day_parser = subparsers.add_parser("process-day")
    day_parser.add_argument("--manifest-path", type=Path, required=True)
    day_parser.add_argument("--market", choices=MARKETS, required=True)
    day_parser.add_argument("--anchor", choices=ANCHOR_DATES, required=True)
    day_parser.add_argument("--output-dir", type=Path, required=True)
    aggregate_parser = subparsers.add_parser("aggregate")
    aggregate_parser.add_argument("--manifest-path", type=Path, required=True)
    aggregate_parser.add_argument("--days-root", type=Path, required=True)
    aggregate_parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "metadata":
        result = acquire_metadata(args.base_url, args.output_dir)
    elif args.command == "process-day":
        result = process_archive(args.manifest_path, args.market, args.anchor, args.output_dir)
    else:
        result = aggregate(args.manifest_path, args.days_root, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
