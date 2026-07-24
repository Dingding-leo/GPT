#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pandas as pd

_EXPECTED_BAR = "1H"
_EXPECTED_STEP_SECONDS = 3_600
_EXPECTED_PROVIDER = "OKX"


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"persisted JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicates,
        )
    except FileNotFoundError as exc:
        raise ValueError(f"required persisted artifact is missing: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"persisted artifact is not valid duplicate-free JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"persisted artifact must contain a JSON object: {path}")
    return payload


def _required_mapping(parent: Mapping[str, Any], key: str, *, label: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}.{key} must be a JSON object")
    return value


def _required_utc_timestamp(value: object, *, label: str) -> pd.Timestamp:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a timezone-aware timestamp string")
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a timezone-aware timestamp string") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError(f"{label} must be a timezone-aware timestamp string")
    return timestamp.tz_convert("UTC")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def verify_intraday_1h_timestamp_grid(output_dir: str | Path) -> dict[str, object]:
    output = Path(output_dir)
    effective_config = _load_json_object(output / "effective_config.json")
    data_config = _required_mapping(effective_config, "data", label="effective_config")
    instrument_id = data_config.get("inst_id")
    if not isinstance(instrument_id, str) or not instrument_id:
        raise ValueError("effective_config.data.inst_id must be a non-empty string")
    if data_config.get("bar") != _EXPECTED_BAR:
        raise ValueError("canonical intraday data bar must be exactly 1H")

    snapshot_dir = output / "snapshot"
    csv_path = snapshot_dir / f"okx-{instrument_id}-{_EXPECTED_BAR}.csv"
    metadata_path = snapshot_dir / f"okx-{instrument_id}-{_EXPECTED_BAR}.metadata.json"
    metadata = _load_json_object(metadata_path)

    if metadata.get("provider") != _EXPECTED_PROVIDER:
        raise ValueError("canonical intraday snapshot provider must be OKX")
    if metadata.get("instrument_id") != instrument_id:
        raise ValueError("snapshot instrument does not match effective configuration")
    if metadata.get("bar") != _EXPECTED_BAR:
        raise ValueError("canonical intraday snapshot bar must be exactly 1H")
    if metadata.get("expected_step_seconds") != _EXPECTED_STEP_SECONDS:
        raise ValueError("canonical intraday snapshot cadence must be exactly 3600 seconds")

    try:
        csv_bytes = csv_path.read_bytes()
    except FileNotFoundError as exc:
        raise ValueError(f"required persisted artifact is missing: {csv_path}") from exc
    expected_csv_sha256 = metadata.get("normalized_csv_sha256")
    if not isinstance(expected_csv_sha256, str) or len(expected_csv_sha256) != 64:
        raise ValueError("snapshot metadata normalized_csv_sha256 must be a SHA-256 digest")
    csv_sha256 = _sha256(csv_bytes)
    if csv_sha256 != expected_csv_sha256:
        raise ValueError("snapshot CSV SHA-256 does not match metadata")

    try:
        frame = pd.read_csv(csv_path, dtype={"timestamp": "string", "confirm": "string"})
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise ValueError("canonical intraday snapshot CSV is unreadable") from exc
    required_columns = {
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume_base",
        "volume_quote",
        "volume_quote_alt",
        "confirm",
    }
    if set(frame.columns) != required_columns:
        raise ValueError("canonical intraday snapshot CSV columns do not match schema")
    if frame.empty:
        raise ValueError("canonical intraday snapshot must contain completed candles")
    if frame["timestamp"].isna().any():
        raise ValueError("canonical intraday snapshot contains a missing timestamp")

    timestamps = pd.DatetimeIndex(
        [
            _required_utc_timestamp(value, label=f"timestamp row {index + 1}")
            for index, value in enumerate(frame["timestamp"].tolist())
        ],
        name="timestamp",
    )
    if timestamps.has_duplicates:
        raise ValueError("canonical intraday snapshot contains duplicate timestamps")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("canonical intraday snapshot timestamps must be strictly increasing")
    if not (timestamps == timestamps.floor("h")).all():
        raise ValueError(
            "canonical intraday snapshot timestamps must align to exact UTC-hour boundaries"
        )
    if len(timestamps) > 1:
        deltas = timestamps[1:] - timestamps[:-1]
        if not (deltas == pd.Timedelta(hours=1)).all():
            raise ValueError("canonical intraday snapshot must have continuous one-hour cadence")
    if not frame["confirm"].eq("1").all():
        raise ValueError("canonical intraday snapshot must contain only confirm=1 candles")

    observations = metadata.get("observations")
    if isinstance(observations, bool) or not isinstance(observations, int):
        raise ValueError("snapshot metadata observations must be an integer")
    if observations != len(frame):
        raise ValueError("snapshot metadata observations do not match the CSV")
    metadata_start = _required_utc_timestamp(metadata.get("start"), label="snapshot metadata start")
    metadata_end = _required_utc_timestamp(metadata.get("end"), label="snapshot metadata end")
    if metadata_start != timestamps[0] or metadata_end != timestamps[-1]:
        raise ValueError("snapshot metadata start/end do not match the CSV timestamp grid")

    return {
        "instrument_id": instrument_id,
        "bar": _EXPECTED_BAR,
        "observations": len(frame),
        "start_utc": timestamps[0].isoformat(),
        "end_utc": timestamps[-1].isoformat(),
        "normalized_csv_sha256": csv_sha256,
        "timestamp_grid": "exact_utc_hour_continuous",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that persisted canonical OKX 1H evidence uses an exact UTC-hour grid."
    )
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def main() -> int:
    evidence = verify_intraday_1h_timestamp_grid(parse_args().output_dir)
    for key, value in evidence.items():
        print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
