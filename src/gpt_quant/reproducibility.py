from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_HEX_DIGITS = frozenset("0123456789abcdef")


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def canonical_json_sha256(value: Any) -> str:
    """Hash a JSON-compatible value using one stable canonical representation."""

    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def file_sha256(path: str | Path) -> str:
    """Hash a persisted artifact without loading the whole file into memory."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_git_commit(value: str) -> bool:
    normalized = value.strip().lower()
    return len(normalized) in {40, 64} and set(normalized) <= _HEX_DIGITS


def resolve_git_commit(repository_root: str | Path = ".") -> str:
    """Resolve the exact checked-out commit, with GITHUB_SHA as a source-archive fallback."""

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(repository_root),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        completed = None

    if completed is not None:
        commit = completed.stdout.strip().lower()
        if _valid_git_commit(commit):
            return commit

    github_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if _valid_git_commit(github_sha):
        return github_sha
    raise RuntimeError("unable to resolve an exact git commit from the checkout or GITHUB_SHA")


def _validate_hashes(name: str, values: Mapping[str, str]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in sorted(values.items()):
        digest = str(value).strip().lower()
        if len(digest) != 64 or not set(digest) <= _HEX_DIGITS:
            raise ValueError(f"{name}[{key!r}] must be a lowercase-compatible SHA-256 digest")
        normalized[str(key)] = digest
    if not normalized:
        raise ValueError(f"{name} cannot be empty")
    return normalized


def _verify_file_hashes(
    expected_hashes: Mapping[str, str],
    paths: Mapping[str, str | Path],
) -> dict[str, str]:
    normalized = _validate_hashes("data_hashes", expected_hashes)
    expected_names = set(normalized)
    path_names = {str(name) for name in paths}
    if path_names != expected_names:
        missing = sorted(expected_names - path_names)
        unexpected = sorted(path_names - expected_names)
        raise ValueError(
            "data_paths keys must exactly match data_hashes keys "
            f"(missing={missing}, unexpected={unexpected})"
        )

    for name, path in sorted(paths.items()):
        actual = file_sha256(path)
        expected = normalized[str(name)]
        if actual != expected:
            raise ValueError(
                f"data hash mismatch for {name!r}: expected {expected}, actual {actual}"
            )
    return normalized


def build_experiment_manifest_entry(
    *,
    effective_config: Mapping[str, Any],
    data_hashes: Mapping[str, str],
    artifact_paths: Mapping[str, str | Path],
    candidate_count: int,
    result_classification: str,
    instrument_id: str,
    bar: str,
    data_paths: Mapping[str, str | Path] | None = None,
    code_commit: str | None = None,
    repository_root: str | Path = ".",
    recorded_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build one auditable record for a completed real-data experiment."""

    if candidate_count < 1:
        raise ValueError("candidate_count must be positive")
    if not result_classification.strip():
        raise ValueError("result_classification cannot be empty")
    if not instrument_id.strip() or not bar.strip():
        raise ValueError("instrument_id and bar cannot be empty")

    commit = (code_commit or resolve_git_commit(repository_root)).strip().lower()
    if not _valid_git_commit(commit):
        raise ValueError("code_commit must be a 40- or 64-character hexadecimal commit id")

    normalized_data_hashes = (
        _verify_file_hashes(data_hashes, data_paths)
        if data_paths is not None
        else _validate_hashes("data_hashes", data_hashes)
    )
    artifact_hashes = _validate_hashes(
        "artifact_hashes",
        {name: file_sha256(path) for name, path in sorted(artifact_paths.items())},
    )
    config_hash = canonical_json_sha256(dict(effective_config))
    experiment_evidence = {
        "schema_version": 1,
        "code_commit": commit,
        "config_sha256": config_hash,
        "data_sha256": normalized_data_hashes,
        "instrument_id": instrument_id,
        "bar": bar,
        "candidate_count": int(candidate_count),
        "result_classification": result_classification,
    }
    experiment_id = f"exp-{canonical_json_sha256(experiment_evidence)[:24]}"
    timestamp = recorded_at_utc or datetime.now(UTC).isoformat()
    run_evidence = {
        "experiment_id": experiment_id,
        "recorded_at_utc": timestamp,
        "artifact_sha256": artifact_hashes,
    }
    run_id = f"run-{canonical_json_sha256(run_evidence)[:24]}"
    return {
        **experiment_evidence,
        **run_evidence,
        "run_id": run_id,
    }


def append_experiment_manifest(
    path: str | Path,
    entry: Mapping[str, Any],
) -> tuple[Path, bool]:
    """Append one canonical JSONL record; exact run IDs are idempotent."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    run_id = str(entry.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("manifest entry must contain a non-empty run_id")

    if output.exists():
        with output.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"manifest contains invalid JSON on line {line_number}"
                    ) from exc
                if not isinstance(existing, dict):
                    raise ValueError(f"manifest line {line_number} is not a JSON object")
                if existing.get("run_id") == run_id:
                    if dict(existing) != dict(entry):
                        raise ValueError(f"manifest run_id collision for {run_id}")
                    return output, False

    with output.open("ab") as handle:
        handle.write(_canonical_json_bytes(dict(entry)))
        handle.flush()
        os.fsync(handle.fileno())
    return output, True
