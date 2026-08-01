#!/usr/bin/env python3
"""Immutable public OKX and Coin Metrics source reconstruction for issue #891."""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

FAMILY_ID = "causal-onchain-transaction-activity-confirmed-e2160-entry-1h-v1"
PROTOCOL_SIGNATURE = (
    FAMILY_ID
    + "|targets=DOGE-USDT,LTC-USDT|activity=doge:TxCnt,ltc:TxCnt"
    + "|activity-lag=24H|windows=adjacent-720H-medians-log1p"
    + "|entry=spot-margin>0&activity-margin>0|exit=spot-margin<=0"
    + "|e2160=close[t-1]/close[t-2161]|daily-00UTC|next-open"
    + "|segment-cash-reset|fee=5bps-one-way|candidate-markets=2|grid=0"
)
MARKETS = (
    {"target": "DOGE-USDT", "asset": "doge"},
    {"target": "LTC-USDT", "asset": "ltc"},
)
OKX_BASE_URL = "https://www.okx.com"
OKX_CANDLE_ENDPOINT = "/api/v5/market/history-candles"
OKX_INSTRUMENT_ENDPOINT = "/api/v5/public/instruments"
CM_BASE_URL = "https://community-api.coinmetrics.io"
CM_ASSET_METRICS_ENDPOINT = "/v4/timeseries/asset-metrics"
BAR = "1H"
CM_FREQUENCY = "1h"
LIMIT = 100
CM_PAGE_SIZE = 10_000
START_MS = int(datetime(2023, 4, 1, tzinfo=timezone.utc).timestamp() * 1000)
END_MS = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
HOUR_MS = 3_600_000
EXPECTED_ROWS = 24_144
WARMUP_END = 2_160
MIN_SIGNAL_INDEX = 2_161
TRAIN_END = 10_800
OOS_END = 23_760
FULL_END = OOS_END
FEE = 0.0005
BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 168
BOOTSTRAP_SEED = 20_260_802
OUT = Path(
    "reports/experiments/causal-onchain-transaction-activity-confirmed-e2160-entry-1h-v1"
)
SOURCE = OUT / "source"
_TIME_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<hour>\d{2}):00:00"
    r"(?:\.0{1,9})?Z$"
)


class SourceContractError(RuntimeError):
    """Immutable provider data violated the preregistered source contract."""


class FetchError(RuntimeError):
    """Transport failed after retries; this is not an economic verdict."""


@dataclass(frozen=True)
class PriceSeries:
    inst_id: str
    open_ms: np.ndarray
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray


@dataclass(frozen=True)
class ActivitySeries:
    asset: str
    open_ms: np.ndarray
    tx_count: np.ndarray


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


def fetch(url: str, *, byte_limit: int, attempts: int = 6) -> bytes:
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
            with urllib.request.urlopen(request, timeout=90) as response:  # noqa: S310
                if response.status != 200:
                    raise FetchError(f"HTTP {response.status} for {url}")
                if response.geturl() != url:
                    raise FetchError(f"redirect rejected: {url} -> {response.geturl()}")
                payload = response.read(byte_limit + 1)
                if not payload or len(payload) > byte_limit:
                    raise FetchError(f"empty or oversized response for {url}")
                return payload
        except urllib.error.HTTPError as exc:
            body = exc.read(min(byte_limit, 65_536))
            if exc.code in {429, 500, 502, 503, 504}:
                last = FetchError(
                    f"transient HTTP {exc.code} for {url}; body_sha256={sha256_bytes(body)}"
                )
            else:
                raise SourceContractError(
                    f"public endpoint rejected fixed request with HTTP {exc.code}: "
                    f"{url}; body_sha256={sha256_bytes(body)}"
                ) from exc
        except (urllib.error.URLError, TimeoutError, FetchError) as exc:
            last = exc
        if attempt + 1 < attempts:
            time.sleep(min(2**attempt, 12))
    raise FetchError(f"public request failed after {attempts} attempts: {url}: {last}")


def parse_json(raw: bytes, *, context: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            raw.decode("utf-8"), object_pairs_hook=reject_duplicate_fields
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceContractError(f"{context}: invalid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise SourceContractError(f"{context}: top-level JSON is not an object")
    return payload


def persist_response(
    *,
    directory: Path,
    filename: str,
    url: str,
    raw: bytes,
    provider: str,
    page: int | None,
) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(raw)
    return {
        "provider": provider,
        "page": page,
        "request_url": url,
        "response_file": str(path),
        "response_bytes": len(raw),
        "response_sha256": sha256_bytes(raw),
    }


def confirm_okx_spot(inst_id: str) -> dict[str, Any]:
    params = urllib.parse.urlencode({"instType": "SPOT", "instId": inst_id})
    url = f"{OKX_BASE_URL}{OKX_INSTRUMENT_ENDPOINT}?{params}"
    raw = fetch(url, byte_limit=1_000_000)
    record = persist_response(
        directory=SOURCE / inst_id,
        filename="instrument.json",
        url=url,
        raw=raw,
        provider="OKX",
        page=None,
    )
    payload = parse_json(raw, context=f"{inst_id} instrument")
    if set(payload) != {"code", "msg", "data"}:
        raise SourceContractError(f"{inst_id} instrument: top-level schema mismatch")
    if payload["code"] != "0" or not isinstance(payload["data"], list):
        raise SourceContractError(f"{inst_id} instrument: unsuccessful public response")
    rows = payload["data"]
    if len(rows) != 1 or not isinstance(rows[0], dict):
        raise SourceContractError(f"{inst_id}: expected one SPOT instrument row")
    row = rows[0]
    if row.get("instId") != inst_id or row.get("instType") != "SPOT":
        raise SourceContractError(f"{inst_id}: instrument identity mismatch")
    if row.get("state") != "live":
        raise SourceContractError(f"{inst_id}: instrument is not live")
    record.update(
        {
            "inst_id": inst_id,
            "inst_type": row.get("instType"),
            "state": row.get("state"),
        }
    )
    return record


def parse_okx_candle_row(
    row: Any, *, inst_id: str, page: int, row_number: int
) -> tuple[int, float, float, float, float, tuple[str, ...]]:
    if not isinstance(row, list) or len(row) != 9:
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: expected 9 fields"
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
    if row[8] != "1":
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: incomplete candle"
        )
    try:
        o, h, low, c = (float(row[index]) for index in range(1, 5))
        volumes = [float(row[index]) for index in (5, 6, 7)]
    except (TypeError, ValueError) as exc:
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: non-numeric candle"
        ) from exc
    if not all(math.isfinite(value) and value > 0 for value in (o, h, low, c)):
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: invalid OHLC"
        )
    if h < max(o, low, c) or low > min(o, h, c):
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: OHLC invariant failure"
        )
    if not all(math.isfinite(value) and value >= 0 for value in volumes):
        raise SourceContractError(
            f"{inst_id} page {page} row {row_number}: invalid volume"
        )
    return timestamp, o, h, low, c, tuple(str(value) for value in row)


def acquire_okx_price(
    inst_id: str,
) -> tuple[PriceSeries, list[dict[str, Any]]]:
    manifest = [confirm_okx_spot(inst_id)]
    cursor = END_MS
    seen: dict[int, tuple[str, ...]] = {}
    values: dict[int, tuple[float, float, float, float]] = {}
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
        url = f"{OKX_BASE_URL}{OKX_CANDLE_ENDPOINT}?{params}"
        raw = fetch(url, byte_limit=1_000_000)
        page_record = persist_response(
            directory=SOURCE / inst_id,
            filename=f"page-{page:04d}.json",
            url=url,
            raw=raw,
            provider="OKX",
            page=page,
        )
        payload = parse_json(raw, context=f"{inst_id} page {page}")
        if set(payload) != {"code", "msg", "data"}:
            raise SourceContractError(
                f"{inst_id} page {page}: top-level schema mismatch"
            )
        if payload["code"] != "0" or not isinstance(payload["data"], list):
            raise SourceContractError(f"{inst_id} page {page}: unsuccessful response")
        rows = payload["data"]
        if not rows:
            raise SourceContractError(
                f"{inst_id}: empty page before requested start at cursor {cursor}"
            )
        parsed = [
            parse_okx_candle_row(
                row,
                inst_id=inst_id,
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
                f"{inst_id} page {page}: timestamp is not before after cursor"
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
        page_record.update(
            {
                "inst_id": inst_id,
                "rows": len(rows),
                "newest": utc_iso(newest),
                "oldest": utc_iso(oldest),
            }
        )
        manifest.append(page_record)
        previous_oldest = oldest
        cursor = oldest
        if oldest <= START_MS:
            break
        time.sleep(0.12)
    else:
        raise SourceContractError(f"{inst_id}: page budget exhausted")

    expected_timestamps = np.arange(START_MS, END_MS, HOUR_MS, dtype=np.int64)
    if len(expected_timestamps) != EXPECTED_ROWS:
        raise RuntimeError("internal expected-row contract mismatch")
    missing = [int(ts) for ts in expected_timestamps if int(ts) not in values]
    observed = sorted(timestamp for timestamp in values if START_MS <= timestamp < END_MS)
    if missing or len(observed) != EXPECTED_ROWS:
        detail = {
            "observed_rows": len(observed),
            "expected_rows": EXPECTED_ROWS,
            "missing_count": len(missing),
            "first_missing": utc_iso(missing[0]) if missing else None,
        }
        raise SourceContractError(f"{inst_id}: exact-grid failure {detail}")
    matrix = np.asarray([values[int(ts)] for ts in expected_timestamps], dtype=np.float64)
    return (
        PriceSeries(
            inst_id=inst_id,
            open_ms=expected_timestamps,
            opens=matrix[:, 0],
            highs=matrix[:, 1],
            lows=matrix[:, 2],
            closes=matrix[:, 3],
        ),
        manifest,
    )


def parse_cm_hour(value: Any, *, asset: str, page: int, row_number: int) -> int:
    if not isinstance(value, str):
        raise SourceContractError(
            f"{asset} page {page} row {row_number}: time is not a string"
        )
    match = _TIME_RE.fullmatch(value)
    if match is None:
        raise SourceContractError(
            f"{asset} page {page} row {row_number}: off-grid time {value!r}"
        )
    dt = datetime.fromisoformat(
        f"{match.group('date')}T{match.group('hour')}:00:00+00:00"
    )
    return int(dt.timestamp() * 1000)


def validate_cm_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "community-api.coinmetrics.io"
        or parsed.path != CM_ASSET_METRICS_ENDPOINT
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise SourceContractError(f"untrusted Coin Metrics page URL: {url}")
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    forbidden = {"api_key", "apikey", "key", "token", "access_token"}
    if forbidden.intersection(name.lower() for name in query):
        raise SourceContractError("credential parameter present in Coin Metrics URL")


def parse_cm_row(
    row: Any, *, asset: str, page: int, row_number: int
) -> tuple[int, float, tuple[tuple[str, Any], ...]]:
    if not isinstance(row, dict):
        raise SourceContractError(
            f"{asset} page {page} row {row_number}: row is not an object"
        )
    allowed = {"asset", "time", "TxCnt", "TxCnt-status", "TxCnt-status-time"}
    if not set(row).issubset(allowed) or not {"asset", "time", "TxCnt"}.issubset(row):
        raise SourceContractError(
            f"{asset} page {page} row {row_number}: row schema mismatch"
        )
    if row["asset"] != asset:
        raise SourceContractError(
            f"{asset} page {page} row {row_number}: unexpected asset {row['asset']!r}"
        )
    timestamp = parse_cm_hour(
        row["time"], asset=asset, page=page, row_number=row_number
    )
    try:
        tx_count = float(row["TxCnt"])
    except (TypeError, ValueError) as exc:
        raise SourceContractError(
            f"{asset} page {page} row {row_number}: invalid TxCnt"
        ) from exc
    if not math.isfinite(tx_count) or tx_count < 0:
        raise SourceContractError(
            f"{asset} page {page} row {row_number}: invalid TxCnt"
        )
    identity = tuple(sorted(row.items()))
    return timestamp, tx_count, identity


def initial_cm_url(asset: str) -> str:
    params = urllib.parse.urlencode(
        {
            "assets": asset,
            "metrics": "TxCnt",
            "frequency": CM_FREQUENCY,
            "start_time": utc_iso(START_MS),
            "end_time": utc_iso(END_MS - HOUR_MS),
            "paging_from": "start",
            "page_size": str(CM_PAGE_SIZE),
        }
    )
    return f"{CM_BASE_URL}{CM_ASSET_METRICS_ENDPOINT}?{params}"


def acquire_coinmetrics_activity(
    asset: str,
) -> tuple[ActivitySeries, list[dict[str, Any]]]:
    url: str | None = initial_cm_url(asset)
    seen_urls: set[str] = set()
    seen_rows: dict[int, tuple[tuple[str, Any], ...]] = {}
    values: dict[int, float] = {}
    manifest: list[dict[str, Any]] = []
    previous_timestamp: int | None = None
    for page in range(1, 20):
        if url is None:
            break
        validate_cm_url(url)
        if url in seen_urls:
            raise SourceContractError(f"{asset}: repeated Coin Metrics page URL")
        seen_urls.add(url)
        raw = fetch(url, byte_limit=20_000_000)
        page_record = persist_response(
            directory=SOURCE / f"coinmetrics-{asset}",
            filename=f"page-{page:04d}.json",
            url=url,
            raw=raw,
            provider="Coin Metrics Community",
            page=page,
        )
        payload = parse_json(raw, context=f"{asset} Coin Metrics page {page}")
        if "data" not in payload or not set(payload).issubset(
            {"data", "next_page_token", "next_page_url"}
        ):
            raise SourceContractError(
                f"{asset} Coin Metrics page {page}: top-level schema mismatch"
            )
        rows = payload["data"]
        if not isinstance(rows, list) or not rows:
            raise SourceContractError(
                f"{asset} Coin Metrics page {page}: empty or invalid data"
            )
        parsed_rows = [
            parse_cm_row(
                row,
                asset=asset,
                page=page,
                row_number=row_number,
            )
            for row_number, row in enumerate(rows, 1)
        ]
        timestamps = [item[0] for item in parsed_rows]
        if any(left >= right for left, right in zip(timestamps, timestamps[1:])):
            raise SourceContractError(
                f"{asset} Coin Metrics page {page}: rows are not strictly ascending"
            )
        if previous_timestamp is not None and timestamps[0] <= previous_timestamp:
            raise SourceContractError(
                f"{asset}: Coin Metrics pagination overlaps or reverses chronology"
            )
        for timestamp, tx_count, identity in parsed_rows:
            prior = seen_rows.get(timestamp)
            if prior is not None and prior != identity:
                raise SourceContractError(
                    f"{asset}: conflicting TxCnt row for {utc_iso(timestamp)}"
                )
            seen_rows.setdefault(timestamp, identity)
            values.setdefault(timestamp, tx_count)
        page_record.update(
            {
                "asset": asset,
                "metric": "TxCnt",
                "frequency": CM_FREQUENCY,
                "rows": len(rows),
                "oldest": utc_iso(timestamps[0]),
                "newest": utc_iso(timestamps[-1]),
            }
        )
        manifest.append(page_record)
        previous_timestamp = timestamps[-1]
        next_page_url = payload.get("next_page_url")
        if next_page_url is None:
            url = None
        elif not isinstance(next_page_url, str) or not next_page_url:
            raise SourceContractError(
                f"{asset} Coin Metrics page {page}: invalid next_page_url"
            )
        else:
            validate_cm_url(next_page_url)
            url = next_page_url
        time.sleep(0.15)
    else:
        raise SourceContractError(f"{asset}: Coin Metrics page budget exhausted")

    expected_timestamps = np.arange(START_MS, END_MS, HOUR_MS, dtype=np.int64)
    missing = [int(ts) for ts in expected_timestamps if int(ts) not in values]
    expected_set = {int(ts) for ts in expected_timestamps}
    observed = sorted(timestamp for timestamp in values if START_MS <= timestamp < END_MS)
    extras = [timestamp for timestamp in observed if timestamp not in expected_set]
    if missing or extras or len(observed) != EXPECTED_ROWS:
        detail = {
            "observed_rows": len(observed),
            "expected_rows": EXPECTED_ROWS,
            "missing_count": len(missing),
            "first_missing": utc_iso(missing[0]) if missing else None,
            "extra_count": len(extras),
        }
        raise SourceContractError(f"{asset}: exact TxCnt grid failure {detail}")
    tx_count = np.asarray([values[int(ts)] for ts in expected_timestamps], dtype=np.float64)
    return (
        ActivitySeries(asset=asset, open_ms=expected_timestamps, tx_count=tx_count),
        manifest,
    )
