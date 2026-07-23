from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .experiment_registry import _registry_lock, load_manifest_entries, validate_manifest_entry


def _canonical_jsonl(entries: list[Mapping[str, Any]]) -> bytes:
    return b"".join(
        (
            json.dumps(dict(entry), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        for entry in entries
    )


def append_experiment_manifest(
    path: str | Path,
    entry: Mapping[str, Any],
) -> tuple[Path, bool]:
    """Append one validated canonical manifest record with idempotent run IDs."""

    validated_entry = validate_manifest_entry(entry)
    output = Path(path)
    with _registry_lock(output):
        existing_entries: list[dict[str, Any]] = []
        if output.exists():
            existing_entries = load_manifest_entries(output)
            if output.read_bytes() != _canonical_jsonl(existing_entries):
                raise ValueError(f"{output} is not canonical JSONL")

        run_id = validated_entry["run_id"]
        for existing in existing_entries:
            if existing["run_id"] != run_id:
                continue
            if existing != validated_entry:
                raise ValueError(f"manifest run_id collision for {run_id}")
            return output, False

        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("ab") as handle:
            handle.write(_canonical_jsonl([validated_entry]))
            handle.flush()
            os.fsync(handle.fileno())
        return output, True
