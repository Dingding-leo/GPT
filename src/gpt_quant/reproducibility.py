from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

_HEX_DIGITS = frozenset("0123456789abcdef")
_CODE_PROVENANCE_KEYS = frozenset(
    {
        "checkout_commit",
        "pull_request_head_commit",
        "pull_request_base_commit",
    }
)
_UNTRACKED_SENSITIVE_ROOTS = frozenset({".github", "config", "scripts", "src", "tests"})
_UNTRACKED_EXECUTABLE_SUFFIXES = frozenset(
    {
        ".bash",
        ".bat",
        ".cmd",
        ".dll",
        ".dylib",
        ".fish",
        ".ipynb",
        ".ps1",
        ".pth",
        ".py",
        ".pyi",
        ".pyw",
        ".pyx",
        ".sh",
        ".so",
        ".zsh",
    }
)
_UNTRACKED_CONFIG_SUFFIXES = frozenset({".cfg", ".ini", ".toml", ".yaml", ".yml"})
_UNTRACKED_ROOT_CONFIG_NAMES = frozenset(
    {
        "Dockerfile",
        "Makefile",
        "Procfile",
        "conftest.py",
        "noxfile.py",
        "pyproject.toml",
        "pytest.ini",
        "setup.cfg",
        "setup.py",
        "sitecustomize.py",
        "tox.ini",
        "usercustomize.py",
    }
)


def _validate_canonical_json_value(value: Any, *, path: str = "$") -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite JSON numbers")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _validate_canonical_json_value(item, path=f"{path}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{path} keys must be strings")
            _validate_canonical_json_value(item, path=f"{path}[{key!r}]")
        return
    raise ValueError(f"{path} must contain only JSON-native values")


def _canonical_json_bytes(value: Any) -> bytes:
    _validate_canonical_json_value(value)
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
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


def _normalize_git_commit(name: str, value: object) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a 40- or 64-character hexadecimal commit id string")
    commit = value.strip().lower()
    if not _valid_git_commit(commit):
        raise ValueError(f"{name} must be a 40- or 64-character hexadecimal commit id")
    return commit


def _validate_non_empty_string(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _normalize_recorded_at_utc(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("recorded_at_utc must be an ISO-8601 string")
    try:
        recorded_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("recorded_at_utc must be an ISO-8601 timestamp") from exc
    if recorded_at.tzinfo is None or recorded_at.utcoffset() is None:
        raise ValueError("recorded_at_utc must include a UTC offset")
    if recorded_at.utcoffset() != timedelta(0):
        raise ValueError("recorded_at_utc must be expressed in UTC")
    if value != recorded_at.isoformat():
        raise ValueError("recorded_at_utc must use canonical UTC ISO-8601 form")
    return value


def _validate_path_mapping(
    name: str,
    values: Mapping[str, str | Path],
) -> dict[str, str | Path]:
    if not isinstance(values, Mapping) or not values:
        raise ValueError(f"{name} must be a non-empty mapping")
    normalized: dict[str, str | Path] = {}
    for key, path in values.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} keys must be non-empty strings")
        if not isinstance(path, (str, Path)):
            raise ValueError(f"{name}[{key!r}] must be a string or Path")
        normalized[key] = path
    return {key: normalized[key] for key in sorted(normalized)}


def _require_clean_tracked_worktree(repository_root: Path) -> None:
    """Reject commit provenance when tracked checkout bytes differ from HEAD."""

    try:
        completed = subprocess.run(
            ["git", "diff", "--quiet", "HEAD", "--"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise RuntimeError("unable to verify tracked worktree cleanliness") from exc

    if completed.returncode == 0:
        return
    if completed.returncode == 1:
        raise RuntimeError(
            "tracked worktree differs from HEAD; refusing to record incomplete code provenance"
        )
    raise RuntimeError("unable to verify tracked worktree cleanliness")


def _untracked_path_can_affect_run(repository_root: Path, relative_path: str) -> bool:
    path = PurePosixPath(relative_path)
    if not path.parts:
        return False
    if path.parts[0] in _UNTRACKED_SENSITIVE_ROOTS:
        return True

    name = path.name
    lowered_name = name.lower()
    if lowered_name == ".env" or lowered_name.startswith(".env."):
        return True
    if path.suffix.lower() in _UNTRACKED_EXECUTABLE_SUFFIXES | _UNTRACKED_CONFIG_SUFFIXES:
        return True
    if len(path.parts) == 1:
        if name in _UNTRACKED_ROOT_CONFIG_NAMES:
            return True
        if lowered_name.startswith(("constraints", "requirements")) and path.suffix.lower() in {
            ".in",
            ".txt",
        }:
            return True

    candidate = repository_root / Path(*path.parts)
    return candidate.is_symlink() or (candidate.is_file() and os.access(candidate, os.X_OK))


def _require_no_untracked_research_inputs(repository_root: Path) -> None:
    """Reject untracked executable or configuration paths while allowing generated reports."""

    try:
        completed = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard", "-z", "--"],
            cwd=repository_root,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise RuntimeError("unable to inspect untracked worktree paths") from exc
    if completed.returncode != 0:
        raise RuntimeError("unable to inspect untracked worktree paths")

    untracked = sorted(os.fsdecode(value) for value in completed.stdout.split(b"\0") if value)
    sensitive = [
        path for path in untracked if _untracked_path_can_affect_run(repository_root, path)
    ]
    if sensitive:
        rendered = ", ".join(repr(path) for path in sensitive[:10])
        if len(sensitive) > 10:
            rendered += f", ... ({len(sensitive) - 10} more)"
        raise RuntimeError(
            "untracked executable or configuration files can affect the run; "
            f"refusing incomplete code provenance: {rendered}"
        )


def resolve_git_commit(repository_root: str | Path = ".") -> str:
    """Resolve the exact checked-out commit, with GITHUB_SHA as a source-archive fallback."""

    root = Path(repository_root)
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
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
            _require_clean_tracked_worktree(root)
            _require_no_untracked_research_inputs(root)
            return commit

    github_sha = os.environ.get("GITHUB_SHA", "").strip().lower()
    if _valid_git_commit(github_sha):
        return github_sha
    raise RuntimeError("unable to resolve an exact git commit from the checkout or GITHUB_SHA")


def _resolve_pull_request_merge_parents(
    repository_root: str | Path,
) -> tuple[str, str]:
    """Resolve the tested base and head from the checked-out PR merge commit."""

    try:
        completed = subprocess.run(
            ["git", "cat-file", "-p", "HEAD"],
            cwd=Path(repository_root),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        raise RuntimeError(
            "unable to resolve tested pull-request base/head from the checkout merge commit"
        ) from exc

    parents = [
        line.removeprefix("parent ").strip().lower()
        for line in completed.stdout.splitlines()
        if line.startswith("parent ")
    ]
    if len(parents) != 2 or not all(_valid_git_commit(parent) for parent in parents):
        raise RuntimeError("pull-request provenance requires a checked-out two-parent merge commit")
    return parents[0], parents[1]


def normalize_code_provenance(
    value: Mapping[str, object],
    *,
    expected_checkout_commit: str | None = None,
) -> dict[str, str]:
    """Validate the tested checkout and optional persistent pull-request revisions."""

    unexpected = sorted(set(value) - _CODE_PROVENANCE_KEYS)
    if unexpected:
        raise ValueError(f"code_provenance contains unsupported keys: {unexpected}")
    if "checkout_commit" not in value:
        raise ValueError("code_provenance must contain checkout_commit")

    normalized = {
        "checkout_commit": _normalize_git_commit(
            "code_provenance.checkout_commit", value["checkout_commit"]
        )
    }
    head_present = "pull_request_head_commit" in value
    base_present = "pull_request_base_commit" in value
    if head_present != base_present:
        raise ValueError(
            "code_provenance pull_request_head_commit and pull_request_base_commit "
            "must be provided together"
        )
    if head_present:
        normalized["pull_request_head_commit"] = _normalize_git_commit(
            "code_provenance.pull_request_head_commit",
            value["pull_request_head_commit"],
        )
        normalized["pull_request_base_commit"] = _normalize_git_commit(
            "code_provenance.pull_request_base_commit",
            value["pull_request_base_commit"],
        )

    if expected_checkout_commit is not None:
        expected = _normalize_git_commit("code_commit", expected_checkout_commit)
        if normalized["checkout_commit"] != expected:
            raise ValueError("code_provenance.checkout_commit must match code_commit")
    return normalized


def resolve_code_provenance(repository_root: str | Path = ".") -> dict[str, str]:
    """Resolve the tested checkout plus persistent PR head/base revisions when applicable."""

    checkout_commit = resolve_git_commit(repository_root)
    provenance = {"checkout_commit": checkout_commit}
    event_name = os.environ.get("GITHUB_EVENT_NAME", "").strip()
    if event_name not in {"pull_request", "pull_request_target"}:
        return provenance

    event_path = os.environ.get("GITHUB_EVENT_PATH", "").strip()
    if not event_path:
        raise RuntimeError(
            "GITHUB_EVENT_PATH is required to resolve pull-request head/base provenance"
        )
    try:
        payload = json.loads(Path(event_path).read_text(encoding="utf-8"))
        pull_request = payload["pull_request"]
        event_head_commit = _normalize_git_commit(
            "pull_request.head.sha", pull_request["head"]["sha"]
        )
        _normalize_git_commit("pull_request.base.sha", pull_request["base"]["sha"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "unable to resolve pull-request head/base commits from GITHUB_EVENT_PATH"
        ) from exc

    tested_base_commit, tested_head_commit = _resolve_pull_request_merge_parents(repository_root)
    if tested_head_commit != event_head_commit:
        raise RuntimeError(
            "checked-out pull-request merge head does not match the event head commit"
        )

    return normalize_code_provenance(
        {
            **provenance,
            "pull_request_head_commit": tested_head_commit,
            "pull_request_base_commit": tested_base_commit,
        },
        expected_checkout_commit=checkout_commit,
    )


def _validate_hashes(name: str, values: Mapping[str, str]) -> dict[str, str]:
    if not isinstance(values, Mapping) or not values:
        raise ValueError(f"{name} must be a non-empty mapping")
    normalized: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{name} keys must be non-empty strings")
        if not isinstance(value, str):
            raise ValueError(f"{name}[{key!r}] must be a SHA-256 digest string")
        digest = value.strip().lower()
        if len(digest) != 64 or not set(digest) <= _HEX_DIGITS:
            raise ValueError(f"{name}[{key!r}] must be a lowercase-compatible SHA-256 digest")
        normalized[key] = digest
    return {key: normalized[key] for key in sorted(normalized)}


def _verify_file_hashes(
    expected_hashes: Mapping[str, str],
    paths: Mapping[str, str | Path],
) -> dict[str, str]:
    normalized = _validate_hashes("data_hashes", expected_hashes)
    normalized_paths = _validate_path_mapping("data_paths", paths)
    expected_names = set(normalized)
    path_names = set(normalized_paths)
    if path_names != expected_names:
        missing = sorted(expected_names - path_names)
        unexpected = sorted(path_names - expected_names)
        raise ValueError(
            "data_paths keys must exactly match data_hashes keys "
            f"(missing={missing}, unexpected={unexpected})"
        )

    for name, path in normalized_paths.items():
        actual = file_sha256(path)
        expected = normalized[name]
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
    code_provenance: Mapping[str, object] | None = None,
    repository_root: str | Path = ".",
    recorded_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build one auditable record for a completed real-data experiment."""

    if (
        not isinstance(candidate_count, int)
        or isinstance(candidate_count, bool)
        or candidate_count < 1
    ):
        raise ValueError("candidate_count must be a positive integer")
    result_classification = _validate_non_empty_string(
        "result_classification", result_classification
    )
    instrument_id = _validate_non_empty_string("instrument_id", instrument_id)
    bar = _validate_non_empty_string("bar", bar)
    timestamp = (
        datetime.now(UTC).isoformat()
        if recorded_at_utc is None
        else _normalize_recorded_at_utc(recorded_at_utc)
    )
    if not isinstance(effective_config, Mapping):
        raise ValueError("effective_config must be a mapping")
    config_hash = canonical_json_sha256(dict(effective_config))
    normalized_data_hashes = _validate_hashes("data_hashes", data_hashes)
    normalized_data_paths = (
        None if data_paths is None else _validate_path_mapping("data_paths", data_paths)
    )
    if normalized_data_paths is not None and set(normalized_data_paths) != set(
        normalized_data_hashes
    ):
        missing = sorted(set(normalized_data_hashes) - set(normalized_data_paths))
        unexpected = sorted(set(normalized_data_paths) - set(normalized_data_hashes))
        raise ValueError(
            "data_paths keys must exactly match data_hashes keys "
            f"(missing={missing}, unexpected={unexpected})"
        )
    normalized_artifact_paths = _validate_path_mapping("artifact_paths", artifact_paths)

    if code_provenance is None:
        if code_commit is None:
            normalized_code_provenance = resolve_code_provenance(repository_root)
        else:
            normalized_code_provenance = normalize_code_provenance(
                {"checkout_commit": code_commit},
                expected_checkout_commit=code_commit,
            )
    else:
        normalized_code_provenance = normalize_code_provenance(
            code_provenance,
            expected_checkout_commit=code_commit,
        )
    commit = normalized_code_provenance["checkout_commit"]

    if normalized_data_paths is not None:
        normalized_data_hashes = _verify_file_hashes(normalized_data_hashes, normalized_data_paths)
    artifact_hashes = _validate_hashes(
        "artifact_hashes",
        {name: file_sha256(path) for name, path in normalized_artifact_paths.items()},
    )
    experiment_evidence = {
        "schema_version": 2,
        "code_commit": commit,
        "code_provenance": normalized_code_provenance,
        "config_sha256": config_hash,
        "data_sha256": normalized_data_hashes,
        "instrument_id": instrument_id,
        "bar": bar,
        "candidate_count": candidate_count,
        "result_classification": result_classification,
    }
    experiment_id = f"exp-{canonical_json_sha256(experiment_evidence)[:24]}"
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
    """Append through the shared strict manifest-validation boundary."""

    from .manifest_io import append_experiment_manifest as append_validated_manifest

    return append_validated_manifest(path, entry)
