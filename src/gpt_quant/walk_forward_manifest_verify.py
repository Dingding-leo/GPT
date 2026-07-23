from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .reproducibility import canonical_json_sha256, file_sha256, resolve_git_commit

_HEX_DIGITS = frozenset("0123456789abcdef")
_REQUIRED_ARTIFACT_KEYS = ("candles", "effective_config", "json", "returns")


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a mapping")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _sha256_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - _HEX_DIGITS:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _sha256_mapping(value: object, label: str) -> dict[str, str]:
    mapping = _mapping(value, label)
    if not mapping:
        raise ValueError(f"{label} cannot be empty")
    normalized: dict[str, str] = {}
    for key, digest in mapping.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{label} keys must be non-empty strings")
        normalized[key] = _sha256_digest(digest, f"{label}[{key!r}]")
    return dict(sorted(normalized.items()))


def _git_commit(value: object) -> str:
    if not isinstance(value, str) or len(value) not in {40, 64} or set(value) - _HEX_DIGITS:
        raise ValueError("manifest code_commit must be a lowercase hexadecimal commit id")
    return value


def _explicit_utc_timestamp(value: object) -> str:
    timestamp = _required_text(value, "manifest recorded_at_utc")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("manifest recorded_at_utc must be a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("manifest recorded_at_utc must include an explicit UTC offset")
    if parsed.utcoffset() != timedelta(0):
        raise ValueError("manifest recorded_at_utc must use UTC")
    parsed.astimezone(UTC)
    return timestamp


def _load_json_mapping(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file():
        raise ValueError(f"{label} is missing")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable") from exc
    return _mapping(payload, label)


def _load_manifest(path: Path) -> list[Mapping[str, Any]]:
    if not path.is_file():
        raise ValueError("experiment manifest is missing")
    entries: list[Mapping[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError("experiment manifest is unreadable") from exc
    for line_number, line in enumerate(lines, start=1):
        if not line:
            raise ValueError(f"experiment manifest contains a blank line at {line_number}")
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"experiment manifest line {line_number} is invalid JSON") from exc
        entries.append(_mapping(entry, f"experiment manifest line {line_number}"))
    if not entries:
        raise ValueError("experiment manifest cannot be empty")
    return entries


def verify_walk_forward_manifest(
    output_dir: str | Path,
    manifest_path: str | Path,
    *,
    repository_root: str | Path = ".",
) -> dict[str, int | str]:
    """Bind persisted walk-forward evidence to one exact manifest entry and checkout."""

    output = Path(output_dir)
    report_path = output / "walk_forward.json"
    returns_path = output / "walk_forward_returns.csv"
    snapshot_dir = output / "snapshot"
    effective_config_path = output / "effective_config.json"

    report = _load_json_mapping(report_path, "walk-forward report")
    effective_config = _load_json_mapping(effective_config_path, "effective configuration")
    data_summary = _mapping(report.get("data_summary"), "walk-forward data_summary")
    provenance = _mapping(data_summary.get("provenance"), "walk-forward provenance")
    settings = _mapping(report.get("settings"), "walk-forward settings")

    instrument_id = _required_text(provenance.get("instrument_id"), "instrument_id")
    bar = _required_text(provenance.get("bar"), "bar")
    snapshot_path = snapshot_dir / f"okx-{instrument_id}-{bar}.csv"
    if not returns_path.is_file() or not snapshot_path.is_file():
        raise ValueError("manifest verification requires persisted returns and normalized snapshot")

    config_data = _mapping(effective_config.get("data"), "effective configuration data")
    if config_data.get("inst_id") != instrument_id or config_data.get("bar") != bar:
        raise ValueError("effective configuration instrument/bar does not match report provenance")
    config_strategy = _mapping(
        effective_config.get("strategy"),
        "effective configuration strategy",
    )
    report_strategy = _mapping(settings.get("base_config"), "walk-forward base_config")
    if config_strategy != report_strategy:
        raise ValueError("effective configuration strategy does not match walk-forward settings")
    robustness = _mapping(
        effective_config.get("robustness"),
        "effective configuration robustness",
    )
    if robustness.get("cost_multipliers") != settings.get("cost_multipliers"):
        raise ValueError("effective configuration cost sensitivities do not match report settings")

    candidate_count = _positive_integer(settings.get("candidate_count"), "candidate_count")
    result_classification = _required_text(
        report.get("robustness_status"),
        "robustness_status",
    )
    actual_artifact_hashes = {
        "candles": file_sha256(snapshot_path),
        "effective_config": file_sha256(effective_config_path),
        "json": file_sha256(report_path),
        "returns": file_sha256(returns_path),
    }
    config_sha256 = canonical_json_sha256(dict(effective_config))
    if actual_artifact_hashes["effective_config"] != config_sha256:
        raise ValueError("effective configuration file is not canonical hash-bound JSON")

    normalized_csv_sha256 = _sha256_digest(
        provenance.get("normalized_csv_sha256"),
        "normalized_csv_sha256",
    )
    if normalized_csv_sha256 != actual_artifact_hashes["candles"]:
        raise ValueError("normalized snapshot hash does not match report provenance")

    matching: list[Mapping[str, Any]] = []
    for entry in _load_manifest(Path(manifest_path)):
        if entry.get("instrument_id") != instrument_id or entry.get("bar") != bar:
            continue
        data_hashes = _mapping(entry.get("data_sha256"), "manifest data_sha256")
        artifact_hashes = _mapping(entry.get("artifact_sha256"), "manifest artifact_sha256")
        if data_hashes.get("normalized_csv") != normalized_csv_sha256:
            continue
        if all(
            artifact_hashes.get(key) == actual_artifact_hashes[key]
            for key in _REQUIRED_ARTIFACT_KEYS
        ):
            matching.append(entry)

    if len(matching) != 1:
        raise ValueError(
            "experiment manifest must contain exactly one entry bound to the persisted report, "
            f"returns, configuration, and normalized snapshot; found {len(matching)}"
        )
    entry = matching[0]
    manifest_schema_version = _positive_integer(
        entry.get("schema_version"), "manifest schema_version"
    )
    if manifest_schema_version != 1:
        raise ValueError(f"unsupported manifest schema_version {manifest_schema_version}")
    manifest_candidate_count = _positive_integer(
        entry.get("candidate_count"),
        "manifest candidate_count",
    )
    if manifest_candidate_count != candidate_count:
        raise ValueError("manifest candidate_count does not match walk-forward settings")
    if entry.get("result_classification") != result_classification:
        raise ValueError("manifest result_classification does not match walk-forward report")
    manifest_config_sha256 = _sha256_digest(
        entry.get("config_sha256"),
        "manifest config_sha256",
    )
    if manifest_config_sha256 != config_sha256:
        raise ValueError("manifest config_sha256 does not match effective configuration")

    manifest_code_commit = _git_commit(entry.get("code_commit"))
    verified_code_commit = resolve_git_commit(repository_root)
    if manifest_code_commit != verified_code_commit:
        raise ValueError("manifest code_commit does not match the verified checkout")

    manifest_data_hashes = _sha256_mapping(entry.get("data_sha256"), "manifest data_sha256")
    manifest_artifact_hashes = _sha256_mapping(
        entry.get("artifact_sha256"), "manifest artifact_sha256"
    )
    experiment_evidence = {
        "schema_version": manifest_schema_version,
        "code_commit": manifest_code_commit,
        "config_sha256": manifest_config_sha256,
        "data_sha256": manifest_data_hashes,
        "instrument_id": instrument_id,
        "bar": bar,
        "candidate_count": manifest_candidate_count,
        "result_classification": result_classification,
    }
    expected_experiment_id = f"exp-{canonical_json_sha256(experiment_evidence)[:24]}"
    manifest_experiment_id = _required_text(entry.get("experiment_id"), "experiment_id")
    if manifest_experiment_id != expected_experiment_id:
        raise ValueError("manifest experiment_id does not match its immutable experiment evidence")

    recorded_at_utc = _explicit_utc_timestamp(entry.get("recorded_at_utc"))
    run_evidence = {
        "experiment_id": expected_experiment_id,
        "recorded_at_utc": recorded_at_utc,
        "artifact_sha256": manifest_artifact_hashes,
    }
    expected_run_id = f"run-{canonical_json_sha256(run_evidence)[:24]}"
    manifest_run_id = _required_text(entry.get("run_id"), "run_id")
    if manifest_run_id != expected_run_id:
        raise ValueError("manifest run_id does not match its immutable run evidence")

    return {
        "manifest_schema_version": manifest_schema_version,
        "manifest_sha256": file_sha256(manifest_path),
        "manifest_experiment_id": manifest_experiment_id,
        "manifest_run_id": manifest_run_id,
        "manifest_code_commit": manifest_code_commit,
        "manifest_candidate_count": candidate_count,
        "manifest_config_sha256": config_sha256,
        "manifest_normalized_csv_sha256": normalized_csv_sha256,
    }
