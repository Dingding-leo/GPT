#!/usr/bin/env python3
"""Immutable OKX source reconstruction for issue #889."""
from __future__ import annotations

import hashlib
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

FAMILY_ID = "causal-same-asset-composite-index-confirmed-e2160-entry-1h-v1"
PROTOCOL_SIGNATURE = (
    FAMILY_ID
    + "|targets=DOGE-USDT,LTC-USDT|index=DOGE-USD,LTC-USD"
    + "|entry=spot_margin>0&index_margin>0|exit=spot_margin<=0"
    + "|window=2160H|daily-00UTC|next-open|segment-cash-reset"
    + "|fee=5bps-one-way|candidate-markets=2|grid=0"
)
MARKETS = (
    {"target": "DOGE-USDT", "index": "DOGE-USD"},
    {"target": "LTC-USDT", "index": "LTC-USD"},
)
BASE_URL = "https://www.okx.com"
SPOT_ENDPOINT = "/api/v5/market/history-candles"
INDEX_ENDPOINT = "/api/v5/market/history-index-candles"
BAR = "1H"
LIMIT = 100
START_MS = int(datetime(2023, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HOUR_MS = 3_600_000
EXPECTED_ROWS = 24_144
WARMUP_END = 2_160
TRAIN_END = 10_800
OOS_END = 23_760
FULL_END = OOS_END
FEE = 0.0005
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20_260_802
OUT = Path(
    "reports/experiments/same-asset-composite-index-confirmed-e2160-entry-1h-v1"
)
SOURCE = OUT / "source"


class SourceContractError(RuntimeError):
    """Immutable provider data violated the preregistered source contract."""


class FetchError(RuntimeError):
    """Transport failed after retries; this is not an economic source verdict."""


@dataclass(frozen=True)
class Series:
    inst_id: str
    endpoint: str
    open_ms: np.ndarray
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray


def utc_iso(ms: int) -> str:
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SourceContractError(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def fetch(url: str, attempts: int = 6) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "causal-1h-strategy-research/1.0",
                },
            )
            with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
                if response.status != 200:
                    raise FetchError(f"HTTP {response.status} for {url}")
                if response.geturl() != url:
                    raise FetchError(f"redirect rejected: {url} -> {response.geturl()}")
                payload = response.read(1_000_001)
                if not payload or len(payload) > 1_000_000:
                    raise FetchError(f"empty or oversized response for {url}")
                return payload
        except (urllib.error.URLError, TimeoutError, FetchError) as exc:
            last = exc
            if attempt + 1 < attempts:
                time.sleep(min(2**attempt, 12))
    raise FetchError(f"public request failed after {attempts} attempts: {url}: {last}")


def parse_payload(raw: bytes, *, inst_id: str, page: int) -> list[list[Any]]:
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=reject_duplicate_fields
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceContractError(f"{inst_id} page {page}: invalid UTF-8 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {"code", "msg", "data"}:
        raise SourceContractError(f"{inst_id} page {page}: top-level schema mismatch")
    if payload["code"] != "0" or not isinstance(payload["msg"], str):
        raise SourceContractError(
            f"{inst_id} page {page}: API code={payload['code']!r} msg={payload['msg']!r}"
        )
    if not isinstance(payload["data"], list):
        raise SourceContractError(f"{inst_id} page {page}: data is not a list")
    return payload["data"]


def parse_row(
    row: Any, *, inst_id: str, endpoint: str, page: int, row_number: int
) -> tuple[int, float, float, float, float, tuple[str, ...]]:
    expected_fields = 9 if endpoint == SPOT_ENDPOINT else 6
    if not isinstance(row, list) or len(row) != expected_fields:
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: expected {expected_fields} fields"
        )
    if not isinstance(row[0], str) or not row[0].isascii() or not row[0].isdigit():
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: invalid timestamp"
        )
    timestamp = int(row[0])
    if timestamp % HOUR_MS:
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: off-hour timestamp {timestamp}"
        )
    confirm = row[8] if endpoint == SPOT_ENDPOINT else row[5]
    if confirm != "1":
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: incomplete candle"
        )
    try:
        o, h, low, c = (float(row[i]) for i in range(1, 5))
    except (TypeError, ValueError) as exc:
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: non-numeric OHLC"
        ) from exc
    if not all(math.isfinite(value) and value > 0 for value in (o, h, low, c)):
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: invalid OHLC"
        )
    if h < max(o, low, c) or low > min(o, h, c):
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: OHLC invariant failure"
        )
    if endpoint == SPOT_ENDPOINT:
        try:
            volumes = tuple(str(row[i]) for i in (5, 6, 7))
            numeric_volumes = [float(value) for value in volumes]
        except (TypeError, ValueError) as exc:
            raise SourceContractError(
                f"{inst_id} page {page} row {row_number}: invalid volume"
            ) from exc
        if not all(math.isfinite(value) and value >= 0 for value in numeric_volumes):
            raise SourceContractError(
                f"{inst_id} page {page} row {row_number}: invalid volume"
            )
    return timestamp, o, h, low, c, tuple(str(value) for value in row)


def acquire_series(inst_id: str, endpoint: str) -> tuple[Series, list[dict[str, Any]]]:
    safe_name = inst_id.replace("/", "-")
    series_dir = SOURCE / safe_name
    series_dir.mkdir(parents=True, exist_ok=True)
    cursor = END_MS
    seen: dict[int, tuple[str, ...]] = {}
    values: dict[int, tuple[float, float, float, float]] = {}
    manifest: list[dict[str, Any]] = []
    previous_oldest: int | None = None
    for page in range(1, 260):
        params = urllib.parse.urlencode(
            {
                "instId": inst_id,
                "bar": BAR,
                "after": str(cursor),
                "limit": str(LIMIT),
            }
        )
        url = f"{BASE_URL}{endpoint}?{params}"
        raw = fetch(url)
        page_path = series_dir / f"page-{page:04d}.json"
        page_path.write_bytes(raw)
        rows = parse_payload(raw, inst_id=inst_id, page=page)
        if not rows:
            raise SourceContractError(
                f"{inst_id}: empty page before requested start at cursor {cursor}"
            )
        parsed = [
            parse_row(
                row,
                inst_id=inst_id,
                endpoint=endpoint,
                page=page,
                row_number=row_number,
            )
            for row_number, row in enumerate(rows, 1)
        ]
        timestamps = [item[0] for item in parsed]
        if any(newer <= older for newer, older in zip(timestamps, timestamps[1:])):
            raise SourceContractError(
                f"{inst_id} page {page}: rows are not strictly newest-to-oldest"
            )
        newest, oldest = timestamps[0], timestamps[-1]
        if newest >= cursor:
            raise SourceContractError(
                f"{inst_id} page {page}: pagination returned timestamp >= after cursor"
            )
        if previous_oldest is not None and oldest >= previous_oldest:
            raise SourceContractError(f"{inst_id}: pagination failed to move backward")
        for timestamp, o, h, low, c, raw_row in parsed:
            prior = seen.get(timestamp)
            if prior is not None and prior != raw_row:
                raise SourceContractError(
                    f"{inst_id}: conflicting row for {utc_iso(timestamp)}"
                )
            seen.setdefault(timestamp, raw_row)
            values.setdefault(timestamp, (o, h, low, c))
        manifest.append(
            {
                "inst_id": inst_id,
                "endpoint": endpoint,
                "page": page,
                "request_url": url,
                "response_file": str(page_path),
                "response_bytes": len(raw),
                "response_sha256": sha256_bytes(raw),
                "rows": len(rows),
                "newest": utc_iso(newest),
                "oldest": utc_iso(oldest),
            }
        )
        previous_oldest = oldest
        cursor = oldest
        if oldest <= START_MS:
            break
        time.sleep(0.23 if endpoint == INDEX_ENDPOINT else 0.12)
    else:
        raise SourceContractError(f"{inst_id}: page budget exhausted")

    expected_timestamps = np.arange(START_MS, END_MS, HOUR_MS, dtype=np.int64)
    if len(expected_timestamps) != EXPECTED_ROWS:
        raise RuntimeError("internal expected-row contract mismatch")
    expected_set = {int(ts) for ts in expected_timestamps}
    missing = [ts for ts in expected_set if ts not in values]
    missing.sort()
    observed_in_range = sorted(ts for ts in values if START_MS <= ts < END_MS)
    extra = [ts for ts in observed_in_range if ts not in expected_set]
    if missing or extra or len(observed_in_range) != EXPECTED_ROWS:
        detail = {
            "observed_rows": len(observed_in_range),
            "expected_rows": EXPECTED_ROWS,
            "first_missing": utc_iso(missing[0]) if missing else None,
            "missing_count": len(missing),
            "extra_count": len(extra),
        }
        raise SourceContractError(f"{inst_id}: exact-grid failure {detail}")
    matrix = np.asarray([values[int(ts)] for ts in expected_timestamps], dtype=np.float64)
    return (
        Series(
            inst_id=inst_id,
            endpoint=endpoint,
            open_ms=expected_timestamps,
            opens=matrix[:, 0],
            highs=matrix[:, 1],
            lows=matrix[:, 2],
            closes=matrix[:, 3],
        ),
        manifest,
    )
