from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
from collections.abc import Callable, Mapping
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
from .okx_execution_quote import (
    _read_public_response,
    _reject_duplicate_fields,
    _required_base_url,
)

RawBytesGetter = Callable[[str, float], bytes]
_ONE_HOUR = pd.Timedelta(hours=1)
_ONE_HOUR_SECONDS = 3_600
_MAX_RESPONSE_BYTES = 1_000_000
_EXPECTED_TOP_LEVEL_KEYS = {"code", "msg", "data"}
_EVIDENCE_PAGE_KEYS = {"payload", "raw_response_base64", "raw_response_sha256"}
_SOURCE_TRANSPORT = "trusted_okx_https_bounded_exact_bytes"
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


def _required_raw_response(value: object) -> bytes:
    if not isinstance(value, bytes) or not value or len(value) > _MAX_RESPONSE_BYTES:
        raise ValueError("OKX history-candles response must be non-empty bounded bytes")
    try:
        value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("OKX history-candles response must be UTF-8 JSON") from exc
    return value


def _parse_history_response(value: bytes) -> dict[str, Any]:
    raw = _required_raw_response(value)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_fields)
    except json.JSONDecodeError as exc:
        raise ValueError("OKX history-candles response is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("OKX history-candles response must be a JSON object")
    if set(payload) != _EXPECTED_TOP_LEVEL_KEYS:
        raise ValueError("OKX history-candles response fields do not match the public schema")
    if not isinstance(payload["code"], str) or not isinstance(payload["msg"], str):
        raise ValueError("OKX history-candles code and message must be strings")
    if not isinstance(payload["data"], list):
        raise ValueError("OKX history-candles data must be a list")
    return dict(payload)


def _evidence_page(payload: Mapping[str, Any], raw_response: bytes) -> dict[str, Any]:
    raw = _required_raw_response(raw_response)
    parsed = _parse_history_response(raw)
    if parsed != dict(payload):
        raise ValueError("OKX history-candles exact response does not match its parsed payload")
    return {
        "payload": parsed,
        "raw_response_base64": base64.b64encode(raw).decode("ascii"),
        "raw_response_sha256": hashlib.sha256(raw).hexdigest(),
    }


def _replay_evidence_page(value: object) -> tuple[dict[str, Any], bytes]:
    if not isinstance(value, Mapping) or set(value) != _EVIDENCE_PAGE_KEYS:
        raise ValueError("persisted OKX 1H source page has an invalid evidence schema")
    encoded = value["raw_response_base64"]
    digest = value["raw_response_sha256"]
    payload = value["payload"]
    if not isinstance(encoded, str) or not encoded.isascii():
        raise ValueError("persisted OKX 1H response bytes must be canonical base64")
    if not isinstance(digest, str) or len(digest) != 64 or digest.lower() != digest:
        raise ValueError("persisted OKX 1H response hash must be a lowercase SHA-256 digest")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("persisted OKX 1H response bytes are not valid base64") from exc
    if base64.b64encode(raw).decode("ascii") != encoded:
        raise ValueError("persisted OKX 1H response bytes are not canonical base64")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError("persisted OKX 1H exact response hash mismatch")
    parsed = _parse_history_response(raw)
    if not isinstance(payload, Mapping) or parsed != dict(payload):
        raise ValueError("persisted OKX 1H exact response does not reproduce its payload")
    return parsed, raw


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
    get_bytes: RawBytesGetter | None = None,
) -> OKXCandleSnapshot:
    """Fetch one exact, complete and replayable OKX spot 1H interval."""

    start_timestamp = _hour_aligned_utc(start, field="start")
    end_timestamp = _hour_aligned_utc(end, field="end")
    if get_json is not None and get_bytes is not None:
        raise ValueError("get_json and get_bytes are mutually exclusive")
    max_pages = derive_okx_one_hour_page_budget(
        start=start_timestamp,
        end=end_timestamp,
        limit=limit,
        safety_pages=safety_pages,
    )

    raw_responses: list[bytes] = []
    normalized_base_url = base_url.rstrip("/")
    strict_getter = get_json
    if strict_getter is None:
        normalized_base_url = _required_base_url(base_url)
        bytes_getter = get_bytes or _read_public_response

        def strict_getter(url: str, request_timeout: float) -> Mapping[str, Any]:
            raw = _required_raw_response(bytes_getter(url, request_timeout))
            payload = _parse_history_response(raw)
            raw_responses.append(raw)
            return payload

    snapshot = fetch_okx_history_candles(
        inst_id=inst_id,
        bar="1H",
        start=start_timestamp,
        end=end_timestamp,
        base_url=normalized_base_url,
        limit=limit,
        max_pages=max_pages,
        pause_seconds=pause_seconds,
        timeout=timeout,
        get_json=strict_getter,
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

    if not raw_responses:
        return snapshot
    if len(raw_responses) != len(snapshot.raw_pages):
        raise ValueError("OKX 1H exact response count does not match parsed response pages")
    evidence_pages = tuple(
        _evidence_page(payload, raw)
        for payload, raw in zip(snapshot.raw_pages, raw_responses, strict=True)
    )
    metadata = dict(snapshot.metadata)
    metadata.update(
        {
            "base_url": normalized_base_url,
            "source_transport": _SOURCE_TRANSPORT,
            "source_response_count": len(raw_responses),
            "source_response_total_bytes": sum(len(raw) for raw in raw_responses),
            "source_response_sha256": [hashlib.sha256(raw).hexdigest() for raw in raw_responses],
            "raw_pages_sha256": hashlib.sha256(_canonical_json_bytes(evidence_pages)).hexdigest(),
        }
    )
    return OKXCandleSnapshot(
        candles=snapshot.candles,
        raw_pages=evidence_pages,
        metadata=metadata,
    )


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
        evidence_pages = json.loads(raw_bytes)
        metadata = json.loads(metadata_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("persisted OKX 1H snapshot contains invalid JSON") from exc
    if not isinstance(evidence_pages, list):
        raise ValueError("persisted OKX 1H raw pages must be a JSON array")
    if not isinstance(metadata, dict):
        raise ValueError("persisted OKX 1H metadata must be a JSON object")
    if metadata.get("instrument_id") != inst_id or metadata.get("bar") != "1H":
        raise ValueError("persisted OKX 1H metadata does not match the requested instrument")
    if hashlib.sha256(csv_bytes).hexdigest() != metadata.get("normalized_csv_sha256"):
        raise ValueError("persisted OKX 1H normalized CSV hash mismatch")
    if hashlib.sha256(raw_bytes).hexdigest() != metadata.get("raw_pages_sha256"):
        raise ValueError("persisted OKX 1H raw-pages hash mismatch")

    replay_payloads: list[dict[str, Any]] = []
    raw_responses: list[bytes] = []
    for page in evidence_pages:
        payload, raw_response = _replay_evidence_page(page)
        replay_payloads.append(payload)
        raw_responses.append(raw_response)
    source_hashes = [hashlib.sha256(raw).hexdigest() for raw in raw_responses]
    if metadata.get("source_transport") != _SOURCE_TRANSPORT:
        raise ValueError("persisted OKX 1H source transport is not the trusted exact-byte contract")
    if metadata.get("source_response_count") != len(raw_responses):
        raise ValueError("persisted OKX 1H source response count mismatch")
    if metadata.get("source_response_total_bytes") != sum(len(raw) for raw in raw_responses):
        raise ValueError("persisted OKX 1H source response byte count mismatch")
    if metadata.get("source_response_sha256") != source_hashes:
        raise ValueError("persisted OKX 1H source response hash inventory mismatch")

    page_index = 0

    def getter(url: str, timeout: float) -> Mapping[str, Any]:
        nonlocal page_index
        if page_index >= len(replay_payloads):
            raise RuntimeError("persisted OKX 1H replay requested an unavailable page")
        page = replay_payloads[page_index]
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
    if page_index != len(replay_payloads):
        raise ValueError("persisted OKX 1H replay did not consume every raw page")
    if _canonical_csv_bytes(replayed.candles) != csv_bytes:
        raise ValueError("persisted OKX 1H normalized CSV does not replay exactly")
    if _canonical_json_bytes(replayed.raw_pages) != _canonical_json_bytes(replay_payloads):
        raise ValueError("persisted OKX 1H parsed pages do not replay exactly")
    for field in _STABLE_METADATA_FIELDS:
        if replayed.metadata.get(field) != metadata.get(field):
            raise ValueError(f"persisted OKX 1H metadata field {field!r} does not replay")

    reconstructed = OKXCandleSnapshot(
        candles=replayed.candles,
        raw_pages=tuple(evidence_pages),
        metadata=metadata,
    )
    _verified_snapshot_bytes(reconstructed)
    return reconstructed
