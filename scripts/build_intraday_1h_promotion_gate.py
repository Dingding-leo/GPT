#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from verify_intraday_1h_profile import verify_intraday_1h_profile

_OUTPUT_NAME = "intraday-promotion-gate.json"
_ACCEPTED_STATUS_PREFIXES = (
    "provisional alpha candidate:",
    "provisional risk-control candidate:",
)
_EXECUTION_BLOCKERS = (
    "maker_order_replay_missing",
    "no_fill_partial_fill_replay_missing",
    "state_recovery_reconciliation_missing",
    "stale_data_kill_switch_evidence_missing",
    "prospective_paper_acceptance_missing",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"required persisted artifact is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"persisted artifact is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"persisted artifact must contain a JSON object: {path}")
    return value


def _require_mapping(parent: Mapping[str, Any], key: str, *, label: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{label}.{key} must be a JSON object")
    return value


def _require_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _require_bool(value: Any, *, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be a boolean")
    return value


def _require_string_sequence(value: Any, *, label: str) -> list[str]:
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise ValueError(f"{label} must be a list of strings")
    parsed = list(value)
    if not all(isinstance(item, str) and item for item in parsed):
        raise ValueError(f"{label} must be a list of strings")
    return parsed


def build_intraday_1h_promotion_gate(output_dir: str | Path) -> dict[str, Any]:
    output = Path(output_dir)
    profile = verify_intraday_1h_profile(output)
    effective_path = output / "effective_config.json"
    report_path = output / "walk_forward.json"
    report = _load_json_object(report_path)

    robustness_status = _require_string(
        report.get("robustness_status"),
        label="walk_forward.robustness_status",
    )
    fold_stability = _require_mapping(report, "fold_stability", label="walk_forward")
    fold_stability_passes = _require_bool(
        fold_stability.get("passes"),
        label="walk_forward.fold_stability.passes",
    )
    fold_failure_reasons = _require_string_sequence(
        fold_stability.get("failure_reasons"),
        label="walk_forward.fold_stability.failure_reasons",
    )
    if fold_stability_passes and fold_failure_reasons:
        raise ValueError("passing fold stability cannot contain failure reasons")
    if not fold_stability_passes and not fold_failure_reasons:
        raise ValueError("rejected fold stability must contain at least one failure reason")

    research_status_passes = robustness_status.startswith(_ACCEPTED_STATUS_PREFIXES)
    research_candidate_eligible = research_status_passes and fold_stability_passes
    research_blockers: list[str] = []
    if not research_status_passes:
        research_blockers.append("research_status_rejected")
    if not fold_stability_passes:
        research_blockers.append("fold_stability_rejected")

    payload = {
        "schema_version": 1,
        "instrument_id": profile["instrument_id"],
        "bar": profile["bar"],
        "modeled_economics": {
            "one_way_exchange_fee_bps": profile["transaction_cost_bps"],
            "cost_multipliers": profile["cost_multipliers"],
            "spread": "separate_not_modeled",
            "slippage": "separate_not_modeled",
            "market_impact": "separate_not_modeled",
            "latency": "separate_not_modeled",
        },
        "source_artifacts": {
            "effective_config_sha256": _sha256_file(effective_path),
            "walk_forward_sha256": _sha256_file(report_path),
        },
        "research_gate": {
            "candidate_count": profile["candidate_count"],
            "robustness_status": robustness_status,
            "fold_stability_passes": fold_stability_passes,
            "fold_failure_reasons": fold_failure_reasons,
            "research_candidate_eligible": research_candidate_eligible,
            "blockers": research_blockers,
        },
        "promotion": {
            "allow_15m_evaluation": research_candidate_eligible,
            "allow_paper_promotion": False,
            "allow_limited_capital": False,
            "paper_blockers": list(_EXECUTION_BLOCKERS),
        },
    }
    output_path = output / _OUTPUT_NAME
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return payload


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish deterministic 1h research-promotion blockers from persisted evidence."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--enforce-research-promotion",
        action="store_true",
        help="Exit nonzero unless the persisted 1h candidate clears the research gate.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_args(argv)
    payload = build_intraday_1h_promotion_gate(arguments.output_dir)
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    if arguments.enforce_research_promotion and not payload["research_gate"][
        "research_candidate_eligible"
    ]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
