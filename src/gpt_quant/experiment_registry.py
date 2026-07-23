from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ._atomic_publish import publish_payloads_atomically
from .reproducibility import canonical_json_sha256, file_sha256

_HEX_DIGITS = frozenset("0123456789abcdef")
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "code_commit",
        "config_sha256",
        "data_sha256",
        "instrument_id",
        "bar",
        "candidate_count",
        "result_classification",
        "experiment_id",
        "recorded_at_utc",
        "artifact_sha256",
        "run_id",
    }
)
_EXPERIMENT_KEYS = (
    "schema_version",
    "code_commit",
    "config_sha256",
    "data_sha256",
    "instrument_id",
    "bar",
    "candidate_count",
    "result_classification",
)


@dataclass(frozen=True, slots=True)
class ExperimentRegistryMergeResult:
    path: Path
    added_runs: int
    skipped_runs: int
    registry_sha256: str


def _canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _validate_digest(name: str, value: object) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - _HEX_DIGITS:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _validate_digest_mapping(name: str, value: object) -> dict[str, str]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{name} must be a non-empty JSON object")
    normalized: dict[str, str] = {}
    for key, digest in sorted(value.items()):
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} keys must be non-empty strings")
        normalized[key] = _validate_digest(f"{name}[{key!r}]", digest)
    return normalized


def _validate_utc_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("recorded_at_utc must be a non-empty string")
    parsed_value = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        timestamp = datetime.fromisoformat(parsed_value)
    except ValueError as exc:
        raise ValueError("recorded_at_utc must be an ISO-8601 timestamp") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("recorded_at_utc must include an explicit UTC offset")
    if timestamp.utcoffset().total_seconds() != 0:
        raise ValueError("recorded_at_utc must use UTC")
    return value


def validate_experiment_manifest_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one canonical manifest entry and independently derive both identities."""

    normalized = dict(entry)
    keys = set(normalized)
    if keys != _MANIFEST_KEYS:
        missing = sorted(_MANIFEST_KEYS - keys)
        unexpected = sorted(keys - _MANIFEST_KEYS)
        raise ValueError(
            "manifest keys must exactly match schema version 1 "
            f"(missing={missing}, unexpected={unexpected})"
        )
    if normalized["schema_version"] != 1:
        raise ValueError("manifest schema_version must equal 1")

    code_commit = normalized["code_commit"]
    if (
        not isinstance(code_commit, str)
        or len(code_commit) not in {40, 64}
        or set(code_commit) - _HEX_DIGITS
    ):
        raise ValueError("code_commit must be a lowercase 40- or 64-character commit id")

    normalized["config_sha256"] = _validate_digest("config_sha256", normalized["config_sha256"])
    normalized["data_sha256"] = _validate_digest_mapping("data_sha256", normalized["data_sha256"])
    normalized["artifact_sha256"] = _validate_digest_mapping(
        "artifact_sha256", normalized["artifact_sha256"]
    )

    for name in ("instrument_id", "bar", "result_classification"):
        value = normalized[name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
    candidate_count = normalized["candidate_count"]
    if isinstance(candidate_count, bool) or not isinstance(candidate_count, int):
        raise ValueError("candidate_count must be an integer")
    if candidate_count < 1:
        raise ValueError("candidate_count must be positive")

    experiment_evidence = {name: normalized[name] for name in _EXPERIMENT_KEYS}
    expected_experiment_id = f"exp-{canonical_json_sha256(experiment_evidence)[:24]}"
    if normalized["experiment_id"] != expected_experiment_id:
        raise ValueError(
            "experiment_id does not match canonical experiment evidence: "
            f"expected {expected_experiment_id}"
        )

    recorded_at_utc = _validate_utc_timestamp(normalized["recorded_at_utc"])
    run_evidence = {
        "experiment_id": expected_experiment_id,
        "recorded_at_utc": recorded_at_utc,
        "artifact_sha256": normalized["artifact_sha256"],
    }
    expected_run_id = f"run-{canonical_json_sha256(run_evidence)[:24]}"
    if normalized["run_id"] != expected_run_id:
        raise ValueError(
            f"run_id does not match canonical run evidence: expected {expected_run_id}"
        )
    return normalized


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key {key!r}")
        value[key] = item
    return value


def _read_manifest(path: Path, *, registry: bool) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"manifest does not exist or is not a regular file: {path}")
    entries: list[dict[str, Any]] = []
    seen_run_ids: set[str] = set()
    for line_number, raw_line in enumerate(path.read_bytes().splitlines(keepends=True), start=1):
        if not raw_line.strip():
            raise ValueError(f"{path} contains a blank line at {line_number}")
        try:
            text = raw_line.decode("utf-8")
            parsed = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path} contains invalid JSON on line {line_number}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(f"{path} line {line_number} is not a JSON object")
        entry = validate_experiment_manifest_entry(parsed)
        if raw_line != _canonical_json_bytes(entry):
            raise ValueError(f"{path} line {line_number} is not canonical JSONL")
        run_id = entry["run_id"]
        if registry and run_id in seen_run_ids:
            raise ValueError(f"registry contains duplicate run_id {run_id}")
        seen_run_ids.add(run_id)
        entries.append(entry)
    if not entries:
        raise ValueError(f"{path} contains no manifest entries")
    return entries


def _experiment_evidence(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {name: entry[name] for name in _EXPERIMENT_KEYS}


def merge_experiment_manifests(
    registry_path: str | Path,
    manifest_paths: Iterable[str | Path],
) -> ExperimentRegistryMergeResult:
    """Atomically merge validated per-run manifests into an ordered durable registry."""

    registry = Path(registry_path)
    inputs = tuple(Path(path) for path in manifest_paths)
    if not inputs:
        raise ValueError("at least one manifest path is required")

    existing = _read_manifest(registry, registry=True) if registry.exists() else []
    merged = list(existing)
    by_run_id = {entry["run_id"]: entry for entry in existing}
    by_experiment_id = {entry["experiment_id"]: _experiment_evidence(entry) for entry in existing}
    added_runs = 0
    skipped_runs = 0

    for manifest in inputs:
        for entry in _read_manifest(manifest, registry=False):
            run_id = entry["run_id"]
            experiment_id = entry["experiment_id"]
            prior_run = by_run_id.get(run_id)
            if prior_run is not None:
                if prior_run != entry:
                    raise ValueError(f"run_id collision for {run_id}")
                skipped_runs += 1
                continue

            experiment_evidence = _experiment_evidence(entry)
            prior_experiment = by_experiment_id.get(experiment_id)
            if prior_experiment is not None and prior_experiment != experiment_evidence:
                raise ValueError(f"experiment_id collision for {experiment_id}")

            merged.append(entry)
            by_run_id[run_id] = entry
            by_experiment_id[experiment_id] = experiment_evidence
            added_runs += 1

    payload = b"".join(_canonical_json_bytes(entry) for entry in merged)
    if added_runs:
        publish_payloads_atomically(
            registry.parent,
            {"registry": registry},
            {"registry": payload},
            commit_order=("registry",),
            staging_prefix=".experiment-registry-",
            error_label="experiment registry",
        )
    return ExperimentRegistryMergeResult(
        path=registry,
        added_runs=added_runs,
        skipped_runs=skipped_runs,
        registry_sha256=file_sha256(registry),
    )
