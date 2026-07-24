#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

_OUTPUT_NAME = "intraday-maker-replay-gate.json"
_EVIDENCE_NAME = "maker-order-replay-gate.json"
_MANIFEST_NAME = "artifact-manifest.sha256"
_REQUIRED_OUTCOMES = ("no_fill", "partial_fill")
_SEPARATE_DIAGNOSTIC = "separate_not_modeled"


def _modeled_economics() -> dict[str, Any]:
    return {
        "one_way_exchange_fee_bps": 5.0,
        "cost_multipliers": [1.0],
        "spread": _SEPARATE_DIAGNOSTIC,
        "slippage": _SEPARATE_DIAGNOSTIC,
        "market_impact": _SEPARATE_DIAGNOSTIC,
        "latency": _SEPARATE_DIAGNOSTIC,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest") from exc
    return value


def _verify_manifest(root: Path) -> Path:
    manifest_path = root / _MANIFEST_NAME
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ValueError("maker replay artifact manifest is missing") from exc
    if not lines:
        raise ValueError("maker replay artifact manifest must not be empty")

    expected_paths: set[str] = set()
    previous_path: str | None = None
    for line in lines:
        expected_digest, separator, relative = line.partition("  ")
        if separator != "  " or len(expected_digest) != 64:
            raise ValueError("maker replay artifact manifest contains a malformed entry")
        try:
            int(expected_digest, 16)
        except ValueError as exc:
            raise ValueError("maker replay artifact manifest contains a non-hex digest") from exc
        pure_relative = PurePosixPath(relative)
        if pure_relative.is_absolute() or not relative or ".." in pure_relative.parts:
            raise ValueError("maker replay artifact manifest path is unsafe")
        if relative in expected_paths or (previous_path is not None and relative <= previous_path):
            raise ValueError("maker replay artifact manifest paths must be unique and sorted")
        expected_paths.add(relative)
        previous_path = relative

        file_path = root.joinpath(*pure_relative.parts)
        if file_path.is_symlink() or not file_path.is_file():
            raise ValueError(f"maker replay artifact file is missing or unsafe: {relative}")
        if not file_path.resolve().is_relative_to(root):
            raise ValueError("maker replay artifact manifest path escapes its root")
        if _sha256_file(file_path) != expected_digest:
            raise ValueError(f"maker replay artifact manifest digest mismatch: {relative}")

    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest_path
    }
    if actual_paths != expected_paths:
        raise ValueError("maker replay artifact manifest file set mismatch")
    return manifest_path


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"required evidence is missing: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"evidence is not valid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"evidence must contain a JSON object: {path.name}")
    return value


def _require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_strings(value: Any, *, label: str) -> list[str]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be a list of strings")
    parsed = list(value)
    if not all(isinstance(item, str) and item for item in parsed):
        raise ValueError(f"{label} must be a list of strings")
    return parsed


def _missing_evidence() -> dict[str, Any]:
    return {
        "evidence_integrity_passes": False,
        "maker_order_replay_passes": False,
        "replay_equivalent": False,
        "artifact_manifest_sha256": None,
        "replay_gate_sha256": None,
        "required_outcomes": list(_REQUIRED_OUTCOMES),
        "observed_outcomes": [],
        "account_connectivity": "disabled",
        "order_submission": "not_performed",
        "blockers": [
            "maker_order_replay_missing",
            "no_fill_partial_fill_replay_missing",
        ],
    }


def _validate_evidence(
    root_value: str | Path,
    *,
    expected_manifest_sha256: str | None,
) -> dict[str, Any]:
    trusted_manifest_sha256 = _require_sha256(
        expected_manifest_sha256,
        label="expected maker replay artifact manifest SHA-256",
    )
    root = Path(root_value).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("maker replay evidence root must be a directory")
    manifest_path = root / _MANIFEST_NAME
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("maker replay artifact manifest is missing or unsafe")
    manifest_sha256 = _sha256_file(manifest_path)
    if manifest_sha256 != trusted_manifest_sha256:
        raise ValueError("maker replay artifact manifest does not match the trusted SHA-256")
    _verify_manifest(root)
    gate_path = root / _EVIDENCE_NAME
    gate = _load_object(gate_path)

    if gate.get("schema_version") != 1:
        raise ValueError("maker replay evidence schema must equal 1")
    economics = gate.get("modeled_economics")
    if not isinstance(economics, Mapping) or dict(economics) != _modeled_economics():
        raise ValueError("maker replay economics must remain exactly 5 bps-only")
    for field in ("evidence_integrity_passes", "maker_order_replay_passes", "replay_equivalent"):
        if not _require_bool(gate.get(field), label=field):
            raise ValueError(f"{field} must pass")

    account = _require_string(gate.get("account_connectivity"), label="account_connectivity")
    submission = _require_string(gate.get("order_submission"), label="order_submission")
    if account != "disabled" or submission != "not_performed":
        raise ValueError("maker replay evidence must remain offline and account-disabled")

    outcomes = _require_strings(gate.get("observed_outcomes"), label="observed_outcomes")
    if len(outcomes) != len(set(outcomes)):
        raise ValueError("observed outcomes must be unique")
    missing = sorted(set(_REQUIRED_OUTCOMES) - set(outcomes))
    if missing:
        raise ValueError(f"maker replay outcomes are incomplete: {', '.join(missing)}")
    blockers = _require_strings(gate.get("blockers"), label="blockers")
    if blockers:
        raise ValueError("passing maker replay evidence cannot contain blockers")

    return {
        "evidence_integrity_passes": True,
        "maker_order_replay_passes": True,
        "replay_equivalent": True,
        "artifact_manifest_sha256": manifest_sha256,
        "replay_gate_sha256": _sha256_file(gate_path),
        "required_outcomes": list(_REQUIRED_OUTCOMES),
        "observed_outcomes": outcomes,
        "account_connectivity": account,
        "order_submission": submission,
        "blockers": [],
    }


def build_gate(
    output_dir: str | Path,
    *,
    evidence_root: str | Path | None = None,
    expected_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    if evidence_root is None:
        if expected_manifest_sha256 is not None:
            raise ValueError("expected manifest SHA-256 requires a maker replay evidence root")
        replay = _missing_evidence()
    else:
        replay = _validate_evidence(
            evidence_root,
            expected_manifest_sha256=expected_manifest_sha256,
        )
    blockers = list(replay["blockers"])
    if replay["maker_order_replay_passes"]:
        blockers.append("state_recovery_reconciliation_missing")
    payload = {
        "schema_version": 1,
        "canonical_timeframe": "1H",
        "benchmark_timeframe": "1Dutc",
        "optional_next_timeframe": "15m",
        "modeled_economics": _modeled_economics(),
        "maker_replay": replay,
        "promotion": {
            "allow_paper_promotion": False,
            "allow_limited_capital": False,
            "blockers": blockers,
        },
    }
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    (output / _OUTPUT_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the fail-closed intraday maker replay gate."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--evidence-root")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--enforce-maker-replay", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    try:
        payload = build_gate(
            arguments.output_dir,
            evidence_root=arguments.evidence_root,
            expected_manifest_sha256=arguments.expected_manifest_sha256,
        )
    except (OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    if arguments.enforce_maker_replay and not payload["maker_replay"]["maker_order_replay_passes"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
