from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
_BASELINE_FEE_BPS = 5.0
_SELECTION_SOURCE = "immutable_normalized_okx_close_and_effective_config_full_5bps_reselection"
_NOT_MODELED_FIELDS = ("spread_model", "slippage_model", "market_impact_model", "latency_model")
_HEX_DIGITS = frozenset("0123456789abcdef")


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _git_sha(value: str, label: str) -> str:
    if not isinstance(value, str) or len(value) != 40 or set(value) - _HEX_DIGITS:
        raise ValueError(f"{label} must be a lowercase 40-character Git SHA")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or set(value) - _HEX_DIGITS:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"verification JSON contains duplicate field {key}")
        result[key] = value
    return result


def _load_verification(path: Path) -> tuple[dict[str, Any], str]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"verification evidence is missing or not a regular file: {path}")
    before = path.read_bytes()
    try:
        payload = json.loads(before.decode("utf-8"), object_pairs_hook=_object_pairs)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"verification evidence is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"verification evidence must be a JSON object: {path}")
    if before != path.read_bytes():
        raise ValueError(f"verification evidence changed during read: {path}")
    return payload, _sha256(before)


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _validate_instrument(
    reports_root: Path,
    instrument: str,
    *,
    tested_sha: str,
) -> dict[str, Any]:
    path = reports_root / instrument / "walk_forward_verification.json"
    payload, verification_sha256 = _load_verification(path)

    if payload.get("status") != "passed":
        raise ValueError(f"{instrument} persisted walk-forward verification did not pass")
    fee = payload.get("transaction_cost_bps")
    if isinstance(fee, bool) or not isinstance(fee, int | float) or not math.isclose(
        float(fee), _BASELINE_FEE_BPS, rel_tol=0.0, abs_tol=1e-12
    ):
        raise ValueError(f"{instrument} is not verified at the 5 bps one-way baseline")
    if payload.get("selection_source") != _SELECTION_SOURCE:
        raise ValueError(f"{instrument} does not prove full 5 bps fold reselection")
    if payload.get("manifest_code_commit") != tested_sha:
        raise ValueError(f"{instrument} verification is not bound to tested revision {tested_sha}")
    if payload.get("verification_schema") != "persisted_walk_forward_v1":
        raise ValueError(f"{instrument} has an unsupported verification schema")

    for field in _NOT_MODELED_FIELDS:
        if payload.get(field) != "not_modeled":
            raise ValueError(f"{instrument} {field} must remain separately not_modeled")

    observations = _positive_integer(payload.get("observations"), f"{instrument} observations")
    folds = _positive_integer(payload.get("folds"), f"{instrument} folds")
    candidates_per_fold = _positive_integer(
        payload.get("selection_candidates_per_fold"),
        f"{instrument} selection_candidates_per_fold",
    )
    exact_counts = {
        "source_price_rows_verified": observations,
        "selected_target_rows_verified": observations,
        "selected_position_rows_verified": observations,
        "selected_folds_verified": folds,
        "selection_folds_verified": folds,
        "selection_candidate_evaluations_verified": folds * candidates_per_fold,
    }
    mismatches = [key for key, expected in exact_counts.items() if payload.get(key) != expected]
    if mismatches:
        raise ValueError(f"{instrument} verification count mismatch: {', '.join(mismatches)}")

    source_sha = _digest(payload.get("source_snapshot_sha256"), f"{instrument} source snapshot")
    if payload.get("manifest_normalized_csv_sha256") != source_sha:
        raise ValueError(f"{instrument} manifest/source snapshot hashes do not match")
    config_sha = _digest(payload.get("effective_config_sha256"), f"{instrument} config")
    if payload.get("manifest_config_sha256") != config_sha:
        raise ValueError(f"{instrument} manifest/effective config hashes do not match")

    return {
        "effective_config_sha256": config_sha,
        "folds_verified": folds,
        "instrument_id": instrument,
        "manifest_run_id": payload.get("manifest_run_id"),
        "observations_verified": observations,
        "report_json_sha256": _digest(
            payload.get("report_json_sha256"), f"{instrument} report JSON"
        ),
        "returns_csv_sha256": _digest(
            payload.get("returns_csv_sha256"), f"{instrument} returns CSV"
        ),
        "source_snapshot_sha256": source_sha,
        "verification_sha256": verification_sha256,
    }


def build_five_bps_walk_forward_evidence(
    reports_root: str | Path,
    *,
    source_head_sha: str,
    tested_sha: str,
) -> dict[str, Any]:
    source_revision = _git_sha(source_head_sha, "source_head_sha")
    tested_revision = _git_sha(tested_sha, "tested_sha")
    root = Path(reports_root).resolve()
    instruments = [
        _validate_instrument(root, instrument, tested_sha=tested_revision)
        for instrument in _INSTRUMENTS
    ]
    return {
        "fee_bps_one_way": _BASELINE_FEE_BPS,
        "head_sha": source_revision,
        "instruments": list(_INSTRUMENTS),
        "instrument_evidence": instruments,
        "latency_model": "not_modeled",
        "market_impact_model": "not_modeled",
        "schema_version": 1,
        "selection_recomputed": True,
        "slippage_model": "not_modeled",
        "spread_model": "not_modeled",
        "status": "pass",
        "tested_sha": tested_revision,
    }


def write_five_bps_walk_forward_evidence(payload: Mapping[str, Any], path: str | Path) -> str:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    ) + b"\n"
    destination.write_bytes(encoded)
    return _sha256(encoded)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build source-bound launch evidence from verified full-selection 5 bps reports."
    )
    parser.add_argument("--reports-root", default="reports/okx")
    parser.add_argument("--source-head-sha", required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument(
        "--output-path",
        default="reports/live_readiness/five_bps_walk_forward.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = build_five_bps_walk_forward_evidence(
        args.reports_root,
        source_head_sha=args.source_head_sha,
        tested_sha=args.tested_sha,
    )
    digest = write_five_bps_walk_forward_evidence(payload, args.output_path)
    print(f"five_bps_evidence_status={payload['status']}")
    print(f"five_bps_evidence_path={args.output_path}")
    print(f"five_bps_evidence_sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
