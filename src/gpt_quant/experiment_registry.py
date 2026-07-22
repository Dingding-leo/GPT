from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, BinaryIO

from .reproducibility import (
    canonical_json_sha256,
    file_sha256,
    normalize_code_provenance,
)

_HEX_DIGITS = frozenset("0123456789abcdef")
_SCHEMA_1_EXPERIMENT_KEYS = (
    "schema_version",
    "code_commit",
    "config_sha256",
    "data_sha256",
    "instrument_id",
    "bar",
    "candidate_count",
    "result_classification",
)
_SCHEMA_2_EXPERIMENT_KEYS = (
    "schema_version",
    "code_commit",
    "code_provenance",
    "config_sha256",
    "data_sha256",
    "instrument_id",
    "bar",
    "candidate_count",
    "result_classification",
)
_RUN_KEYS = ("experiment_id", "recorded_at_utc", "artifact_sha256")


@dataclass(frozen=True, slots=True)
class RegistryUpdate:
    registry_path: Path
    existing_runs: int
    appended_runs: int
    skipped_runs: int
    total_runs: int
    registry_sha256: str


def _canonical_line(entry: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(dict(entry), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _canonical_registry(entries: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(_canonical_line(entry) for entry in entries)


def _validate_digest(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a SHA-256 digest string")
    digest = value.strip().lower()
    if len(digest) != 64 or not set(digest) <= _HEX_DIGITS:
        raise ValueError(f"{name} must be a SHA-256 digest string")
    return digest


def _validate_hash_mapping(name: str, value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a non-empty mapping")
    normalized: dict[str, str] = {}
    for key, digest in value.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} keys must be non-empty strings")
        normalized[key] = _validate_digest(f"{name}[{key!r}]", digest)
    return {key: normalized[key] for key in sorted(normalized)}


def _parse_recorded_at_utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("recorded_at_utc must be an ISO-8601 string")
    raw_value = value
    try:
        recorded_at = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("recorded_at_utc must be an ISO-8601 timestamp") from exc
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at_utc must include a UTC offset")
    if recorded_at.utcoffset() != timedelta(0):
        raise ValueError("recorded_at_utc must be expressed in UTC")
    if raw_value != recorded_at.isoformat():
        raise ValueError("recorded_at_utc must use canonical UTC ISO-8601 form")
    return recorded_at


def _experiment_keys(entry: Mapping[str, Any]) -> tuple[str, ...]:
    schema_version = entry.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        raise ValueError("schema_version must be an integer")
    if schema_version == 1:
        return _SCHEMA_1_EXPERIMENT_KEYS
    if schema_version == 2:
        return _SCHEMA_2_EXPERIMENT_KEYS
    raise ValueError(f"unsupported schema_version: {schema_version}")


def _validate_non_empty_string(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def validate_manifest_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    experiment_keys = _experiment_keys(entry)
    expected_keys = (*experiment_keys, *_RUN_KEYS, "run_id")
    missing = [key for key in expected_keys if key not in entry]
    if missing:
        raise ValueError(f"manifest entry is missing required keys: {missing}")
    unexpected = sorted(set(entry) - set(expected_keys))
    if unexpected:
        raise ValueError(f"manifest entry contains unsupported keys: {unexpected}")

    normalized = dict(entry)
    code_commit = _validate_non_empty_string("code_commit", normalized["code_commit"])
    code_commit = code_commit.strip().lower()
    if len(code_commit) not in {40, 64} or not set(code_commit) <= _HEX_DIGITS:
        raise ValueError("code_commit must be a 40- or 64-character hexadecimal commit id")
    normalized["code_commit"] = code_commit
    if normalized["schema_version"] == 2:
        code_provenance = normalized["code_provenance"]
        if not isinstance(code_provenance, Mapping):
            raise ValueError("code_provenance must be a mapping")
        normalized["code_provenance"] = normalize_code_provenance(
            code_provenance,
            expected_checkout_commit=code_commit,
        )
    normalized["config_sha256"] = _validate_digest("config_sha256", normalized["config_sha256"])
    normalized["data_sha256"] = _validate_hash_mapping("data_sha256", normalized["data_sha256"])
    normalized["artifact_sha256"] = _validate_hash_mapping(
        "artifact_sha256", normalized["artifact_sha256"]
    )
    candidate_count = normalized["candidate_count"]
    if (
        not isinstance(candidate_count, int)
        or isinstance(candidate_count, bool)
        or candidate_count < 1
    ):
        raise ValueError("candidate_count must be a positive integer")
    normalized["instrument_id"] = _validate_non_empty_string(
        "instrument_id", normalized["instrument_id"]
    )
    normalized["bar"] = _validate_non_empty_string("bar", normalized["bar"])
    normalized["result_classification"] = _validate_non_empty_string(
        "result_classification", normalized["result_classification"]
    )
    normalized["experiment_id"] = _validate_non_empty_string(
        "experiment_id", normalized["experiment_id"]
    )
    normalized["run_id"] = _validate_non_empty_string("run_id", normalized["run_id"])

    _parse_recorded_at_utc(normalized["recorded_at_utc"])

    experiment_evidence = {key: normalized[key] for key in experiment_keys}
    expected_experiment_id = f"exp-{canonical_json_sha256(experiment_evidence)[:24]}"
    if normalized["experiment_id"] != expected_experiment_id:
        raise ValueError("experiment_id does not match the experiment evidence")

    run_evidence = {key: normalized[key] for key in _RUN_KEYS}
    expected_run_id = f"run-{canonical_json_sha256(run_evidence)[:24]}"
    if normalized["run_id"] != expected_run_id:
        raise ValueError("run_id does not match the run evidence")
    return normalized


def load_manifest_entries(
    path: str | Path,
    *,
    missing_ok: bool = False,
    require_canonical: bool = False,
) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        if missing_ok:
            return []
        raise FileNotFoundError(source)

    entries: list[dict[str, Any]] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{source} contains invalid JSON on line {line_number}") from exc
            if not isinstance(parsed, dict):
                raise ValueError(f"{source} line {line_number} is not a JSON object")
            entries.append(validate_manifest_entry(parsed))
    if require_canonical and source.read_bytes() != _canonical_registry(entries):
        raise ValueError(f"{source} is not canonical JSONL")
    return entries


def _load_registry_entries(path: Path) -> list[dict[str, Any]]:
    return load_manifest_entries(path, missing_ok=True, require_canonical=True)


def _experiment_evidence(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {key: entry[key] for key in _experiment_keys(entry)}


def _registry_sort_key(entry: Mapping[str, Any]) -> tuple[datetime, str]:
    return _parse_recorded_at_utc(entry["recorded_at_utc"]), str(entry["run_id"])


def _lock_path(registry: Path) -> Path:
    return registry.with_name(f".{registry.name}.lock")


def _acquire_registry_lock(handle: BinaryIO) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    if os.name == "nt":
        import msvcrt

        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        return
    raise RuntimeError(f"cross-process registry locking is unsupported on os.name={os.name!r}")


def _release_registry_lock(handle: BinaryIO) -> None:
    if os.name == "posix":
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    raise RuntimeError(f"cross-process registry locking is unsupported on os.name={os.name!r}")


@contextmanager
def _registry_lock(registry: Path) -> Iterator[None]:
    """Serialize read-merge-replace transactions across local processes."""

    registry.parent.mkdir(parents=True, exist_ok=True)
    with _lock_path(registry).open("a+b") as handle:
        _acquire_registry_lock(handle)
        try:
            yield
        finally:
            _release_registry_lock(handle)


def _fsync_directory(path: Path) -> None:
    """Persist a completed atomic rename on filesystems with POSIX directory fsync."""

    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _write_registry_atomic(path: Path, entries: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.tmp-",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(_canonical_registry(entries))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _merge_experiment_manifests_locked(
    registry: Path,
    manifest_paths: tuple[Path, ...],
) -> RegistryUpdate:
    existing = _load_registry_entries(registry)
    by_run: dict[str, dict[str, Any]] = {}
    by_experiment: dict[str, dict[str, Any]] = {}

    for entry in existing:
        run_id = str(entry["run_id"])
        experiment_id = str(entry["experiment_id"])
        if run_id in by_run:
            raise ValueError(f"registry contains duplicate run_id {run_id}")
        evidence = _experiment_evidence(entry)
        if experiment_id in by_experiment and by_experiment[experiment_id] != evidence:
            raise ValueError(f"registry contains experiment_id collision for {experiment_id}")
        by_run[run_id] = entry
        by_experiment[experiment_id] = evidence

    additions: list[dict[str, Any]] = []
    skipped = 0
    for source in sorted(manifest_paths, key=lambda path: str(path)):
        for entry in load_manifest_entries(source, require_canonical=True):
            run_id = str(entry["run_id"])
            experiment_id = str(entry["experiment_id"])
            evidence = _experiment_evidence(entry)
            if experiment_id in by_experiment and by_experiment[experiment_id] != evidence:
                raise ValueError(f"experiment_id collision for {experiment_id}")
            if run_id in by_run:
                if by_run[run_id] != entry:
                    raise ValueError(f"run_id collision for {run_id}")
                skipped += 1
                continue
            by_run[run_id] = entry
            by_experiment[experiment_id] = evidence
            additions.append(entry)

    combined = sorted([*existing, *additions], key=_registry_sort_key)
    canonical_registry = _canonical_registry(combined)
    if not registry.exists() or registry.read_bytes() != canonical_registry:
        _write_registry_atomic(registry, combined)
    return RegistryUpdate(
        registry_path=registry,
        existing_runs=len(existing),
        appended_runs=len(additions),
        skipped_runs=skipped,
        total_runs=len(existing) + len(additions),
        registry_sha256=file_sha256(registry),
    )


def merge_experiment_manifests(
    registry_path: str | Path,
    manifest_paths: Iterable[str | Path],
) -> RegistryUpdate:
    registry = Path(registry_path)
    sources = tuple(Path(path) for path in manifest_paths)
    with _registry_lock(registry):
        return _merge_experiment_manifests_locked(registry, sources)
