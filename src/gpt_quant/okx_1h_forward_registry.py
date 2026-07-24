from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

import pandas as pd

from .okx import _canonical_csv_bytes
from .okx_1h import replay_persisted_okx_one_hour_snapshot

_SCHEMA_VERSION = 1
_JOURNAL_NAME = "okx-1h-forward-registry.jsonl"
_DESCRIPTOR_NAME = "snapshot-descriptor.json"
_ONE_HOUR = pd.Timedelta(hours=1)
_SAFE_INSTRUMENT = re.compile(r"^[A-Z0-9-]+$")
_VOLATILE_REACQUISITION_METADATA_FIELDS = frozenset({"fetched_at_utc"})
_RECORD_KEYS = {
    "schema_version",
    "provider",
    "market_type",
    "instrument_id",
    "bar",
    "snapshot_id",
    "snapshot_start_utc",
    "snapshot_end_utc",
    "observations",
    "normalized_csv_sha256",
    "raw_pages_sha256",
    "metadata_sha256",
    "previous_record_id",
    "previous_snapshot_id",
    "overlap_start_utc",
    "overlap_end_utc",
    "overlap_observations",
    "overlap_csv_sha256",
    "appended_start_utc",
    "appended_end_utc",
    "appended_observations",
    "record_id",
}
_DESCRIPTOR_KEYS = {
    "schema_version",
    "provider",
    "market_type",
    "instrument_id",
    "bar",
    "snapshot_start_utc",
    "snapshot_end_utc",
    "observations",
    "normalized_csv_sha256",
    "raw_pages_sha256",
    "metadata_sha256",
    "snapshot_id",
}


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"forward registry contains duplicate field {key!r}")
        value[key] = item
    return value


def _required_sha256(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or value.lower() != value
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _required_instrument_id(inst_id: str) -> str:
    if not isinstance(inst_id, str) or not _SAFE_INSTRUMENT.fullmatch(inst_id):
        raise ValueError("instrument_id must contain only uppercase letters, digits and hyphens")
    return inst_id


def _timestamp(value: object, *, field: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a valid UTC timestamp") from exc
    if pd.isna(timestamp) or timestamp.tzinfo is None:
        raise ValueError(f"{field} must be a timezone-aware UTC timestamp")
    timestamp = timestamp.tz_convert("UTC")
    if timestamp != timestamp.floor("h"):
        raise ValueError(f"{field} must align to an exact UTC hour")
    return timestamp


def _timestamp_text(value: pd.Timestamp) -> str:
    return value.tz_convert("UTC").isoformat().replace("+00:00", "Z")


def _snapshot_paths(snapshot_dir: Path, inst_id: str) -> dict[str, Path]:
    stem = f"okx-{inst_id}-1H"
    return {
        "csv": snapshot_dir / f"{stem}.csv",
        "raw": snapshot_dir / f"{stem}.raw.json",
        "metadata": snapshot_dir / f"{stem}.metadata.json",
    }


def _snapshot_descriptor(snapshot_dir: Path, inst_id: str) -> tuple[dict[str, Any], Any]:
    snapshot = replay_persisted_okx_one_hour_snapshot(snapshot_dir, inst_id=inst_id)
    paths = _snapshot_paths(snapshot_dir, inst_id)
    metadata_bytes = paths["metadata"].read_bytes()
    start = _timestamp(snapshot.metadata["start"], field="snapshot start")
    end = _timestamp(snapshot.metadata["end"], field="snapshot end")
    descriptor: dict[str, Any] = {
        "schema_version": _SCHEMA_VERSION,
        "provider": "OKX",
        "market_type": "spot",
        "instrument_id": inst_id,
        "bar": "1H",
        "snapshot_start_utc": _timestamp_text(start),
        "snapshot_end_utc": _timestamp_text(end),
        "observations": len(snapshot.candles),
        "normalized_csv_sha256": _required_sha256(
            snapshot.metadata.get("normalized_csv_sha256"),
            field="normalized_csv_sha256",
        ),
        "raw_pages_sha256": _required_sha256(
            snapshot.metadata.get("raw_pages_sha256"),
            field="raw_pages_sha256",
        ),
        "metadata_sha256": _sha256(metadata_bytes),
    }
    descriptor["snapshot_id"] = _sha256(_canonical_json_bytes(descriptor))
    return descriptor, snapshot


def _write_once_or_same(path: Path, payload: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with suppress(OSError):
        path.parent.chmod(0o700)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise FileExistsError(
                f"refusing to replace different immutable registry evidence: {path}"
            )
        return
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(handle.name, mode)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _append_line(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with suppress(OSError):
        path.parent.chmod(0o700)
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ValueError("forward registry journal must be a regular file")
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        written = os.write(descriptor, payload)
        if written != len(payload):
            raise OSError("short write while appending forward registry journal")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _parse_record_line(line: bytes) -> dict[str, Any]:
    try:
        value = json.loads(line.decode("utf-8"), object_pairs_hook=_reject_duplicate_fields)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("forward registry journal contains invalid JSON") from exc
    if not isinstance(value, Mapping) or set(value) != _RECORD_KEYS:
        raise ValueError("forward registry record has an invalid schema")
    record = dict(value)
    if _canonical_json_bytes(record) != line:
        raise ValueError("forward registry record is not canonical JSON")
    claimed_id = _required_sha256(record["record_id"], field="record_id")
    payload = dict(record)
    del payload["record_id"]
    if _sha256(_canonical_json_bytes(payload)) != claimed_id:
        raise ValueError("forward registry record ID mismatch")
    return record


def _read_records(journal_path: Path) -> list[dict[str, Any]]:
    if not journal_path.exists():
        return []
    if journal_path.is_symlink() or not journal_path.is_file():
        raise ValueError("forward registry journal must be a regular file")
    raw = journal_path.read_bytes()
    if raw and not raw.endswith(b"\n"):
        raise ValueError("forward registry journal contains a truncated final record")
    lines = raw.splitlines(keepends=True)
    records = [_parse_record_line(line) for line in lines]
    previous_record_id: str | None = None
    previous_snapshot_id: str | None = None
    for record in records:
        if record["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("forward registry schema version is unsupported")
        if record["provider"] != "OKX" or record["market_type"] != "spot":
            raise ValueError("forward registry provider boundary is invalid")
        if record["bar"] != "1H":
            raise ValueError("forward registry bar must remain 1H")
        if record["previous_record_id"] != previous_record_id:
            raise ValueError("forward registry record chain is broken")
        if record["previous_snapshot_id"] != previous_snapshot_id:
            raise ValueError("forward registry snapshot chain is broken")
        previous_record_id = record["record_id"]
        previous_snapshot_id = record["snapshot_id"]
    return records


def _registry_instrument_dir(registry_dir: str | Path, inst_id: str) -> Path:
    root = Path(registry_dir)
    if root.is_symlink():
        raise ValueError("forward registry root must not be a symlink")
    return root / _required_instrument_id(inst_id)


def _stored_snapshot_dir(instrument_dir: Path, snapshot_id: str) -> Path:
    return instrument_dir / "snapshots" / snapshot_id


def _persist_snapshot(
    *,
    source_dir: Path,
    destination_dir: Path,
    inst_id: str,
    descriptor: Mapping[str, Any],
) -> None:
    source_paths = _snapshot_paths(source_dir, inst_id)
    destination_paths = _snapshot_paths(destination_dir, inst_id)
    for key in ("csv", "raw", "metadata"):
        _write_once_or_same(destination_paths[key], source_paths[key].read_bytes())
    _write_once_or_same(destination_dir / _DESCRIPTOR_NAME, _canonical_json_bytes(descriptor))


def _same_window_reacquisition(previous: Any, current: Any) -> bool:
    if not previous.candles.equals(current.candles):
        return False
    if previous.raw_pages != current.raw_pages:
        return False
    previous_metadata = {
        key: value
        for key, value in previous.metadata.items()
        if key not in _VOLATILE_REACQUISITION_METADATA_FIELDS
    }
    current_metadata = {
        key: value
        for key, value in current.metadata.items()
        if key not in _VOLATILE_REACQUISITION_METADATA_FIELDS
    }
    return previous_metadata == current_metadata


def _compare_snapshots(previous: Any, current: Any) -> dict[str, Any]:
    previous_start = _timestamp(previous.metadata["start"], field="previous snapshot start")
    previous_end = _timestamp(previous.metadata["end"], field="previous snapshot end")
    current_start = _timestamp(current.metadata["start"], field="current snapshot start")
    current_end = _timestamp(current.metadata["end"], field="current snapshot end")
    if current_start != previous_start:
        raise ValueError("forward 1H snapshot changed its immutable start boundary")
    if current_end <= previous_end:
        raise ValueError("forward 1H snapshot must extend beyond the previous completed hour")
    overlap = current.candles.loc[previous_start:previous_end]
    if not overlap.equals(previous.candles):
        raise ValueError("forward 1H snapshot changed a previously completed overlap bar")
    appended_start = previous_end + _ONE_HOUR
    appended = current.candles.loc[appended_start:current_end]
    expected = int((current_end - previous_end) / _ONE_HOUR)
    if len(appended) != expected or appended.index[0] != appended_start:
        raise ValueError("forward 1H snapshot omitted an expected completed bar")
    return {
        "overlap_start_utc": _timestamp_text(previous_start),
        "overlap_end_utc": _timestamp_text(previous_end),
        "overlap_observations": len(previous.candles),
        "overlap_csv_sha256": _sha256(_canonical_csv_bytes(previous.candles)),
        "appended_start_utc": _timestamp_text(appended_start),
        "appended_end_utc": _timestamp_text(current_end),
        "appended_observations": len(appended),
    }


def _record_payload(
    descriptor: Mapping[str, Any],
    *,
    previous_record: Mapping[str, Any] | None,
    transition: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if transition is None:
        start = descriptor["snapshot_start_utc"]
        end = descriptor["snapshot_end_utc"]
        transition = {
            "overlap_start_utc": None,
            "overlap_end_utc": None,
            "overlap_observations": 0,
            "overlap_csv_sha256": None,
            "appended_start_utc": start,
            "appended_end_utc": end,
            "appended_observations": descriptor["observations"],
        }
    payload = {
        **descriptor,
        "previous_record_id": None if previous_record is None else previous_record["record_id"],
        "previous_snapshot_id": None if previous_record is None else previous_record["snapshot_id"],
        **transition,
    }
    record_id = _sha256(_canonical_json_bytes(payload))
    return {**payload, "record_id": record_id}


def replay_okx_one_hour_forward_registry(
    registry_dir: str | Path,
    *,
    inst_id: str,
) -> tuple[dict[str, Any], ...]:
    """Verify an append-only 1H snapshot chain and every persisted source artifact."""

    instrument_dir = _registry_instrument_dir(registry_dir, inst_id)
    records = _read_records(instrument_dir / _JOURNAL_NAME)
    previous_snapshot: Any | None = None
    previous_record: Mapping[str, Any] | None = None
    for record in records:
        if record["instrument_id"] != inst_id:
            raise ValueError("forward registry record instrument mismatch")
        snapshot_id = _required_sha256(record["snapshot_id"], field="snapshot_id")
        stored_dir = _stored_snapshot_dir(instrument_dir, snapshot_id)
        descriptor_path = stored_dir / _DESCRIPTOR_NAME
        try:
            descriptor = json.loads(
                descriptor_path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_fields,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                "forward registry snapshot descriptor is unavailable or invalid"
            ) from exc
        if not isinstance(descriptor, Mapping) or set(descriptor) != _DESCRIPTOR_KEYS:
            raise ValueError("forward registry snapshot descriptor has an invalid schema")
        if descriptor_path.read_bytes() != _canonical_json_bytes(descriptor):
            raise ValueError("forward registry snapshot descriptor is not canonical")
        replayed_descriptor, snapshot = _snapshot_descriptor(stored_dir, inst_id)
        if dict(descriptor) != replayed_descriptor:
            raise ValueError("forward registry snapshot descriptor does not match source artifacts")
        for field in _DESCRIPTOR_KEYS:
            if record[field] != descriptor[field]:
                raise ValueError(f"forward registry record field {field!r} mismatches its snapshot")
        transition = (
            None if previous_snapshot is None else _compare_snapshots(previous_snapshot, snapshot)
        )
        expected_record = _record_payload(
            descriptor,
            previous_record=previous_record,
            transition=transition,
        )
        if record != expected_record:
            raise ValueError("forward registry transition evidence does not replay")
        previous_snapshot = snapshot
        previous_record = record
    return tuple(records)


def register_okx_one_hour_forward_snapshot(
    snapshot_dir: str | Path,
    registry_dir: str | Path,
    *,
    inst_id: str,
) -> dict[str, Any]:
    """Persist one exact 1H snapshot and fail closed on overlap or cadence drift."""

    inst_id = _required_instrument_id(inst_id)
    source_dir = Path(snapshot_dir)
    descriptor, current_snapshot = _snapshot_descriptor(source_dir, inst_id)
    instrument_dir = _registry_instrument_dir(registry_dir, inst_id)
    existing = replay_okx_one_hour_forward_registry(registry_dir, inst_id=inst_id)
    if existing and existing[-1]["snapshot_id"] == descriptor["snapshot_id"]:
        return dict(existing[-1])
    previous_record = existing[-1] if existing else None
    transition: dict[str, Any] | None = None
    if previous_record is not None:
        previous_dir = _stored_snapshot_dir(instrument_dir, previous_record["snapshot_id"])
        previous_snapshot = replay_persisted_okx_one_hour_snapshot(previous_dir, inst_id=inst_id)
        if _same_window_reacquisition(previous_snapshot, current_snapshot):
            return dict(previous_record)
        transition = _compare_snapshots(previous_snapshot, current_snapshot)
    record = _record_payload(
        descriptor,
        previous_record=previous_record,
        transition=transition,
    )
    destination = _stored_snapshot_dir(instrument_dir, descriptor["snapshot_id"])
    _persist_snapshot(
        source_dir=source_dir,
        destination_dir=destination,
        inst_id=inst_id,
        descriptor=descriptor,
    )
    _append_line(instrument_dir / _JOURNAL_NAME, _canonical_json_bytes(record))
    replayed = replay_okx_one_hour_forward_registry(registry_dir, inst_id=inst_id)
    if not replayed or replayed[-1] != record:
        raise ValueError("forward registry append did not replay exactly")
    return record
