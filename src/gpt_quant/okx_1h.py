from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

from .okx import (
    JSONGetter,
    OKXCandleSnapshot,
    _canonical_csv_bytes,
    _canonical_json_bytes,
    _verified_snapshot_bytes,
    fetch_okx_history_candles,
)

_ONE_HOUR = pd.Timedelta(hours=1)
_ONE_HOUR_SECONDS = 3_600
_STABLE_METADATA_FIELDS = frozenset(
    {
        "provider",
        "endpoint",
        "base_url",
        "instrument_id",
        "bar",
        "requested_start",
        "requested_end",
        "freshness_checked_at_utc",
        "freshness_age_seconds",
        "freshness_max_age_seconds",
        "limit",
        "max_pages",
        "pages",
        "pagination_termination",
        "pagination_complete",
        "requested_start_reached",
        "raw_rows",
        "parsed_rows",
        "duplicates_removed",
        "incomplete_rows_removed",
        "observations",
        "start",
        "end",
        "expected_step_seconds",
        "missing_intervals",
        "normalized_csv_sha256",
        "raw_pages_sha256",
        "limitations",
    }
)


def _hour_aligned_utc(value: pd.Timestamp | str, *, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a valid timestamp") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{field} must be a valid timestamp")
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    if timestamp != timestamp.floor("h"):
        raise ValueError(f"{field} must align to an exact UTC hour")
    return timestamp


def derive_okx_one_hour_page_budget(
    *,
    start: pd.Timestamp | str,
    end: pd.Timestamp | str,
    limit: int = 100,
    safety_pages: int = 2,
) -> int:
    """Return a deterministic page budget for inclusive completed 1H coverage."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer in [1, 100]")
    if isinstance(safety_pages, bool) or not isinstance(safety_pages, int) or safety_pages < 1:
        raise ValueError("safety_pages must be a positive integer")
    start_timestamp = _hour_aligned_utc(start, field="start")
    end_timestamp = _hour_aligned_utc(end, field="end")
    if start_timestamp > end_timestamp:
        raise ValueError("start must not be after end")
    expected_observations = int((end_timestamp - start_timestamp) / _ONE_HOUR) + 1
    return math.ceil(expected_observations / limit) + safety_pages


def fetch_okx_one_hour_candles(
    *,
    inst_id: str,
    start: pd.Timestamp | str,
    end: pd.Timestamp | str,
    base_url: str = "https://www.okx.com",
    limit: int = 100,
    pause_seconds: float = 0.12,
    timeout: float = 20.0,
    safety_pages: int = 2,
    get_json: JSONGetter | None = None,
) -> OKXCandleSnapshot:
    """Fetch one exact, complete and replayable OKX spot 1H interval."""

    start_timestamp = _hour_aligned_utc(start, field="start")
    end_timestamp = _hour_aligned_utc(end, field="end")
    max_pages = derive_okx_one_hour_page_budget(
        start=start_timestamp,
        end=end_timestamp,
        limit=limit,
        safety_pages=safety_pages,
    )
    snapshot = fetch_okx_history_candles(
        inst_id=inst_id,
        bar="1H",
        start=start_timestamp,
        end=end_timestamp,
        base_url=base_url,
        limit=limit,
        max_pages=max_pages,
        pause_seconds=pause_seconds,
        timeout=timeout,
        get_json=get_json,
    )
    metadata = snapshot.metadata
    if metadata.get("requested_start_reached") is not True:
        raise ValueError("OKX 1H history did not reach the requested start boundary")
    if metadata.get("expected_step_seconds") != _ONE_HOUR_SECONDS:
        raise ValueError("OKX 1H snapshot has an invalid declared cadence")
    if metadata.get("missing_intervals") not in (0, None):
        raise ValueError("OKX 1H snapshot contains missing intervals")
    if snapshot.candles.index[0] != start_timestamp:
        raise ValueError("OKX 1H snapshot does not start at the requested boundary")
    if snapshot.candles.index[-1] != end_timestamp:
        raise ValueError("OKX 1H snapshot does not end at the requested boundary")
    expected_observations = int((end_timestamp - start_timestamp) / _ONE_HOUR) + 1
    if len(snapshot.candles) != expected_observations:
        raise ValueError("OKX 1H snapshot observation count does not match its boundaries")
    if any(timestamp != timestamp.floor("h") for timestamp in snapshot.candles.index):
        raise ValueError("OKX 1H snapshot contains a candle not aligned to an exact UTC hour")
    return snapshot


def replay_persisted_okx_one_hour_snapshot(
    snapshot_dir: str | Path,
    *,
    inst_id: str,
) -> OKXCandleSnapshot:
    """Reconstruct a persisted OKX 1H snapshot solely from its exact stored bytes."""

    directory = Path(snapshot_dir)
    stem = f"okx-{inst_id.replace('/', '-')}-1H"
    csv_path = directory / f"{stem}.csv"
    raw_path = directory / f"{stem}.raw.json"
    metadata_path = directory / f"{stem}.metadata.json"
    csv_bytes = csv_path.read_bytes()
    raw_bytes = raw_path.read_bytes()
    metadata_bytes = metadata_path.read_bytes()
    try:
        raw_pages = json.loads(raw_bytes)
        metadata = json.loads(metadata_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("persisted OKX 1H snapshot contains invalid JSON") from exc
    if not isinstance(raw_pages, list) or not all(isinstance(page, dict) for page in raw_pages):
        raise ValueError("persisted OKX 1H raw pages must be a JSON array of objects")
    if not isinstance(metadata, dict):
        raise ValueError("persisted OKX 1H metadata must be a JSON object")
    if metadata.get("instrument_id") != inst_id or metadata.get("bar") != "1H":
        raise ValueError("persisted OKX 1H metadata does not match the requested instrument")
    if hashlib.sha256(csv_bytes).hexdigest() != metadata.get("normalized_csv_sha256"):
        raise ValueError("persisted OKX 1H normalized CSV hash mismatch")
    if hashlib.sha256(raw_bytes).hexdigest() != metadata.get("raw_pages_sha256"):
        raise ValueError("persisted OKX 1H raw-pages hash mismatch")

    page_index = 0

    def getter(url: str, timeout: float) -> Mapping[str, Any]:
        nonlocal page_index
        if page_index >= len(raw_pages):
            raise RuntimeError("persisted OKX 1H replay requested an unavailable page")
        page = raw_pages[page_index]
        page_index += 1
        return page

    replayed = fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=metadata["requested_start"],
        end=metadata["requested_end"],
        base_url=metadata["base_url"],
        limit=metadata["limit"],
        pause_seconds=0.0,
        timeout=20.0,
        safety_pages=metadata["max_pages"]
        - math.ceil(metadata["observations"] / metadata["limit"]),
        get_json=getter,
    )
    if page_index != len(raw_pages):
        raise ValueError("persisted OKX 1H replay did not consume every raw page")
    if _canonical_csv_bytes(replayed.candles) != csv_bytes:
        raise ValueError("persisted OKX 1H normalized CSV does not replay exactly")
    if _canonical_json_bytes(replayed.raw_pages) != raw_bytes:
        raise ValueError("persisted OKX 1H raw pages do not replay exactly")
    for field in _STABLE_METADATA_FIELDS:
        if replayed.metadata.get(field) != metadata.get(field):
            raise ValueError(f"persisted OKX 1H metadata field {field!r} does not replay")

    reconstructed = OKXCandleSnapshot(
        candles=replayed.candles,
        raw_pages=replayed.raw_pages,
        metadata=metadata,
    )
    _verified_snapshot_bytes(reconstructed)
    return reconstructed
