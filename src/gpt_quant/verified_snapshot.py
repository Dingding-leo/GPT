from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .reproducibility import file_sha256

_HEX_DIGITS = frozenset("0123456789abcdef")
_REQUIRED_MANIFEST_FIELDS = {
    "schema_version",
    "provider",
    "market_type",
    "instrument_id",
    "timeframe",
    "schema",
    "observations",
    "start",
    "end",
    "data_path",
    "data_sha256",
    "provenance",
}


@dataclass(frozen=True)
class VerifiedPriceSnapshot:
    """One manifest-bound external price series that passed strict provenance checks."""

    manifest_path: Path
    data_path: Path
    provider: str
    market_type: str
    instrument_id: str
    timeframe: str
    data_sha256: str
    observations: int
    start: pd.Timestamp
    end: pd.Timestamp
    timestamp_column: str
    close_column: str
    provenance: dict[str, Any]
    prices: pd.Series


def _require_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _parse_aware_timestamp(value: object, name: str, *, require_utc: bool = False) -> pd.Timestamp:
    text = _require_text(value, name)
    try:
        timestamp = pd.Timestamp(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a valid timestamp") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must include an explicit timezone")
    if require_utc and timestamp.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
    return timestamp.tz_convert("UTC")


def _validate_provenance(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError("provenance must be a non-empty JSON object")
    provenance = dict(value)
    has_retrieval_time = "retrieved_at_utc" in provenance
    has_workflow_source = "source_workflow_run_id" in provenance
    if not has_retrieval_time and not has_workflow_source:
        raise ValueError("provenance must include retrieved_at_utc or source_workflow_run_id")
    if has_retrieval_time:
        _parse_aware_timestamp(provenance["retrieved_at_utc"], "retrieved_at_utc", require_utc=True)
    for name in ("source_workflow_run_id", "source_artifact_id"):
        if name in provenance:
            item = provenance[name]
            if isinstance(item, bool) or not isinstance(item, int) or item < 1:
                raise ValueError(f"provenance.{name} must be a positive integer")
    if "source_artifact_sha256" in provenance:
        digest = _require_text(
            provenance["source_artifact_sha256"], "provenance.source_artifact_sha256"
        ).lower()
        if len(digest) != 64 or set(digest) - _HEX_DIGITS:
            raise ValueError("provenance.source_artifact_sha256 must be a SHA-256 digest")
    return provenance


def _resolve_data_path(manifest_path: Path, value: object) -> Path:
    relative = Path(_require_text(value, "data_path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("data_path must be a relative path without parent traversal")
    base_directory = manifest_path.parent.resolve()
    try:
        data_path = (base_directory / relative).resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(base_directory / relative) from exc
    try:
        data_path.relative_to(base_directory)
    except ValueError as exc:
        raise ValueError("data_path resolves outside the manifest directory") from exc
    if not data_path.is_file():
        raise ValueError("data_path must resolve to a regular file")
    return data_path


def _load_manifest(path: str | Path) -> tuple[Path, dict[str, Any]]:
    try:
        manifest_path = Path(path).resolve(strict=True)
    except FileNotFoundError as exc:
        raise FileNotFoundError(Path(path)) from exc
    if not manifest_path.is_file():
        raise ValueError("snapshot manifest must be a regular file")
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("snapshot manifest is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("snapshot manifest must contain a JSON object")
    missing = sorted(_REQUIRED_MANIFEST_FIELDS - set(value))
    if missing:
        raise ValueError(f"snapshot manifest is missing required fields: {missing}")
    return manifest_path, value


def load_verified_price_snapshot(path: str | Path) -> VerifiedPriceSnapshot:
    """Load external CSV prices only after strict manifest and byte-level validation."""

    manifest_path, manifest = _load_manifest(path)
    if isinstance(manifest["schema_version"], bool) or manifest["schema_version"] != 1:
        raise ValueError("snapshot manifest schema_version must equal 1")

    provider = _require_text(manifest["provider"], "provider")
    market_type = _require_text(manifest["market_type"], "market_type")
    instrument_id = _require_text(manifest["instrument_id"], "instrument_id")
    timeframe = _require_text(manifest["timeframe"], "timeframe")
    provenance = _validate_provenance(manifest["provenance"])

    schema = manifest["schema"]
    if not isinstance(schema, dict):
        raise ValueError("schema must be a JSON object")
    columns = schema.get("columns")
    if (
        not isinstance(columns, list)
        or not columns
        or any(not isinstance(column, str) or not column for column in columns)
        or len(set(columns)) != len(columns)
    ):
        raise ValueError("schema.columns must be a non-empty list of unique names")
    timestamp_column = _require_text(schema.get("timestamp_column"), "schema.timestamp_column")
    close_column = _require_text(schema.get("close_column"), "schema.close_column")
    if timestamp_column == close_column:
        raise ValueError("timestamp and close columns must be different")
    if timestamp_column not in columns or close_column not in columns:
        raise ValueError("timestamp and close columns must be present in schema.columns")

    observations = manifest["observations"]
    if isinstance(observations, bool) or not isinstance(observations, int) or observations < 1:
        raise ValueError("observations must be a positive integer")
    expected_start = _parse_aware_timestamp(manifest["start"], "start")
    expected_end = _parse_aware_timestamp(manifest["end"], "end")
    if expected_start > expected_end:
        raise ValueError("start must not be after end")

    data_path = _resolve_data_path(manifest_path, manifest["data_path"])
    expected_hash = _require_text(manifest["data_sha256"], "data_sha256").lower()
    if len(expected_hash) != 64 or set(expected_hash) - _HEX_DIGITS:
        raise ValueError("data_sha256 must be a SHA-256 digest")
    actual_hash = file_sha256(data_path)
    if actual_hash != expected_hash:
        raise ValueError(f"data SHA-256 mismatch: expected {expected_hash}, actual {actual_hash}")

    try:
        frame = pd.read_csv(data_path, dtype=str, keep_default_na=False)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise ValueError("snapshot CSV could not be parsed") from exc
    if list(frame.columns) != columns:
        raise ValueError(
            f"CSV columns do not match manifest schema: expected {columns}, "
            f"actual {list(frame.columns)}"
        )
    if len(frame) != observations:
        raise ValueError(
            f"CSV observation count mismatch: expected {observations}, actual {len(frame)}"
        )

    timestamps: list[pd.Timestamp] = []
    for row_number, value in enumerate(frame[timestamp_column], start=2):
        timestamps.append(_parse_aware_timestamp(value, f"CSV timestamp on row {row_number}"))
    index = pd.DatetimeIndex(timestamps, name=timestamp_column)
    if index.has_duplicates:
        raise ValueError("CSV timestamps must be unique")
    if not index.is_monotonic_increasing:
        raise ValueError("CSV timestamps must be strictly increasing")

    try:
        closes = frame[close_column].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("CSV closes must be numeric") from exc
    if not np.isfinite(closes).all():
        raise ValueError("CSV closes must be finite")
    if (closes <= 0).any():
        raise ValueError("CSV closes must be strictly positive")

    if index[0] != expected_start:
        raise ValueError("CSV first timestamp does not match manifest start")
    if index[-1] != expected_end:
        raise ValueError("CSV last timestamp does not match manifest end")

    prices = pd.Series(closes, index=index, name="close")
    return VerifiedPriceSnapshot(
        manifest_path=manifest_path,
        data_path=data_path,
        provider=provider,
        market_type=market_type,
        instrument_id=instrument_id,
        timeframe=timeframe,
        data_sha256=actual_hash,
        observations=observations,
        start=expected_start,
        end=expected_end,
        timestamp_column=timestamp_column,
        close_column=close_column,
        provenance=provenance,
        prices=prices,
    )
