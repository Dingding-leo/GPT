from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .experiment_registry import (
    _fsync_directory,
    _lock_path,
    _registry_lock,
    load_manifest_entries,
    validate_manifest_entry,
)


def _canonical_jsonl(entries: list[Mapping[str, Any]]) -> bytes:
    return b"".join(
        (
            json.dumps(dict(entry), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        for entry in entries
    )


def _validate_owned_file(path: Path, *, label: str) -> None:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symbolic link")
    if not path.exists():
        return
    if not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    if path.stat().st_nlink > 1:
        raise ValueError(f"{label} must not be a hard-linked file")


def _validate_manifest_publication_path(path: Path) -> None:
    if path.parent.is_symlink():
        raise ValueError("manifest output directory must not be a symbolic link")
    _validate_owned_file(path, label="manifest destination")
    _validate_owned_file(_lock_path(path), label="manifest lock")


def _write_manifest_atomic(path: Path, payload: bytes) -> None:
    _validate_manifest_publication_path(path)
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
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _validate_manifest_publication_path(path)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def append_experiment_manifest(
    path: str | Path,
    entry: Mapping[str, Any],
) -> tuple[Path, bool]:
    """Atomically append one validated canonical record with idempotent run IDs."""

    validated_entry = validate_manifest_entry(entry)
    output = Path(path)
    _validate_manifest_publication_path(output)
    with _registry_lock(output):
        _validate_manifest_publication_path(output)
        existing_entries: list[dict[str, Any]] = []
        existing_payload = b""
        if output.exists():
            existing_entries = load_manifest_entries(output)
            existing_payload = output.read_bytes()
            if existing_payload != _canonical_jsonl(existing_entries):
                raise ValueError(f"{output} is not canonical JSONL")

        run_id = validated_entry["run_id"]
        for existing in existing_entries:
            if existing["run_id"] != run_id:
                continue
            if existing != validated_entry:
                raise ValueError(f"manifest run_id collision for {run_id}")
            return output, False

        payload = existing_payload + _canonical_jsonl([validated_entry])
        _write_manifest_atomic(output, payload)
        return output, True
