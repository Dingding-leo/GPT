from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-same-asset-confirmation-channel-closure-1h-v1"
RESEARCH_PARENT = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"


def build_evidence() -> dict[str, Any]:
    groups = [
        {
            "group_id": "same_asset_composite_index_e2160_confirmation",
            "source_issue": 889,
            "source_pull_request": 890,
            "exact_head": "15c7fdebe09f3c4ae8f5e7971f8f9f5b03cd4eb6",
            "workflow_run": 30706543671,
            "artifact_id": 8820561525,
            "artifact_sha256": "2f3542bbbaa27a77c4e3cecbb35abc44164d86de1291e7b3b4fa58d742396672",
            "evidence_sha256": "15f0fab0b62fdb41b3c7436cbf6ef0af4fd8ba6eeb1d01570123d69d94581a3a",
            "targets": ["DOGE-USDT", "LTC-USDT"],
            "source_contract_executable": True,
            "training_decisions_per_market": 360,
            "training_entry_vetoes": {"DOGE-USDT": 0, "LTC-USDT": 0},
            "materially_altered_bilateral_training_decisions": False,
            "training_quarter_breadth_established": False,
            "genuinely_distinct_information": False,
            "distinctness_classification": "numerically_distinct_but_directionally_redundant",
            "spot_index_margin_correlation": {
                "DOGE-USDT": 0.999997184,
                "LTC-USDT": 0.999990741,
            },
            "performance_accessed": False,
            "bilateral_fee_clearing_benchmark_relative_performance": "not_established",
            "positive_dependence_aware_lower_bounds": "not_established",
            "fold_year_breadth": "not_established",
            "one_hour_latency_transport": "not_established",
            "supportive": False,
            "rejection_type": "information_redundancy_before_oos",
        },
        {
            "group_id": "same_asset_onchain_txcnt_confirmation",
            "source_issue": 891,
            "source_pull_request": 893,
            "exact_head": "7f057d8679f1797cd7f8973f962ab37dff41ef22",
            "workflow_run": 30708866223,
            "artifact_id": 8821217482,
            "evidence_sha256": "4e036f804ef1efc9ba20845c18e9f07edf2cb629d63801ec9be26a9262658a38",
            "report_sha256": "62dd8c1253a9601d3fabd5c19eed96064041e8ee0cdeb1bfaf4b198639260392",
            "targets": ["DOGE-USDT", "LTC-USDT"],
            "provider": "Coin Metrics Community",
            "metric": "TxCnt",
            "frequency": "1h",
            "fixed_request_period": ["2023-04-01T00:00:00Z", "2025-12-31T23:00:00Z"],
            "source_contract_executable": False,
            "source_failure": {
                "asset": "doge",
                "http_status": 400,
                "tested_page_sizes": [10000, 2000],
                "identical_response_body_sha256": "40a4a5ffb815160e10c7ee51e0dfe188dd19b6f021b91ab7c9a299d63b49e9f1",
            },
            "materially_altered_bilateral_training_decisions": "not_established",
            "training_quarter_breadth_established": "not_established",
            "genuinely_distinct_information": "not_established",
            "performance_accessed": False,
            "bilateral_fee_clearing_benchmark_relative_performance": "not_established",
            "positive_dependence_aware_lower_bounds": "not_established",
            "fold_year_breadth": "not_established",
            "one_hour_latency_transport": "not_established",
            "supportive": False,
            "rejection_type": "immutable_public_source_contract_failure_before_features",
        },
    ]
    gates = {
        "two_of_two_groups_have_executable_exact_public_sources": False,
        "one_of_two_groups_materially_alters_bilateral_training_decisions": False,
        "one_of_two_groups_establishes_bilateral_fee_clearing_benchmark_relative_performance": False,
        "one_of_two_groups_establishes_positive_dependence_aware_lower_bounds": False,
        "one_of_two_groups_establishes_broad_fold_year_and_latency_transport": False,
        "leave_one_group_out_still_leaves_one_supportive_group": False,
        "support_does_not_depend_on_posthoc_source_or_market_changes": True,
    }
    leave_one_out = {
        "omit_same_asset_composite_index_e2160_confirmation": {
            "remaining_supportive_groups": 0,
            "family_support_retained": False,
        },
        "omit_same_asset_onchain_txcnt_confirmation": {
            "remaining_supportive_groups": 0,
            "family_support_retained": False,
        },
    }
    return {
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "family_id": FAMILY_ID,
        "classification": "completed_evidence_strategy_family_closure",
        "research_parent": RESEARCH_PARENT,
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "architecture_group_count": 2,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_oos_consumed": 0,
        "performance_recomputed": False,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral": False,
        "credentials_used": False,
        "accounts_accessed": False,
        "orders_placed": False,
        "groups": groups,
        "supportive_group_count": 0,
        "source_executable_group_count": 1,
        "material_training_decision_group_count": 0,
        "performance_supported_group_count": 0,
        "dependence_supported_group_count": 0,
        "breadth_latency_supported_group_count": 0,
        "family_gates": gates,
        "family_gates_passed": sum(bool(value) for value in gates.values()),
        "family_gate_count": len(gates),
        "leave_one_group_out": leave_one_out,
        "failure_diagnosis": {
            "group_a": "source-valid but information-redundant: the exogenous index never changed a training entry decision",
            "group_b": "orthogonal premise but unusable under the frozen credential-free public source contract",
            "economic_rejection_claimed": False,
            "reason": "neither group reached authorised bilateral performance evaluation",
        },
        "closed_rescue_paths": [
            "alternate OKX composite-index confirmation horizons or windows on the consumed contracts",
            "alternate Coin Metrics Community TxCnt windows, lags, thresholds or target subsets on the consumed contracts",
            "market-subset selection after inspection",
            "same-source sign reversal or threshold rescue",
        ],
        "correction_permitted": False,
        "correction_applied": False,
        "observation_epoch_restarted": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": "reject_causal_public_same_asset_confirmation_channel",
        "next_strategy_action": "keep both exact same-asset confirmation channels closed and preregister a materially different executable causal information source before any acquisition or performance access",
    }


def write_outputs(output_dir: Path, evidence: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    (output_dir / "evidence.json").write_bytes(payload)
    (output_dir / "evidence.sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n")
    lines = [
        "# Public same-asset confirmation-channel closure",
        "",
        f"- Family: `{evidence['family_id']}`",
        f"- Architecture groups: `{evidence['architecture_group_count']}`",
        f"- New candidates / market data / OOS: `{evidence['candidate_count']} / {evidence['new_market_data']} / {evidence['new_oos_consumed']}`",
        f"- Supportive groups: `{evidence['supportive_group_count']}/2`",
        f"- Family gates passed: `{evidence['family_gates_passed']}/{evidence['family_gate_count']}`",
        f"- Verdict: `{evidence['verdict']}`",
        "",
        "## Group disposition",
        "",
        "| Group | Source executable | Material training decisions | Performance accessed | Supportive | Rejection type |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for group in evidence["groups"]:
        lines.append(
            f"| {group['group_id']} | {group['source_contract_executable']} | "
            f"{group['materially_altered_bilateral_training_decisions']} | {group['performance_accessed']} | "
            f"{group['supportive']} | {group['rejection_type']} |"
        )
    lines.extend([
        "",
        "## Diagnosis",
        "",
        f"- Composite-index group: {evidence['failure_diagnosis']['group_a']}.",
        f"- On-chain TxCnt group: {evidence['failure_diagnosis']['group_b']}.",
        "- No economic rejection is claimed because neither group reached authorised bilateral performance evaluation.",
        "",
        "## Machine-readable verdict",
        "",
        "```json",
        json.dumps(
            {
                "family_id": evidence["family_id"],
                "supportive_group_count": evidence["supportive_group_count"],
                "family_gates_passed": evidence["family_gates_passed"],
                "family_gate_count": evidence["family_gate_count"],
                "correction_permitted": evidence["correction_permitted"],
                "observation_epoch_restarted": evidence["observation_epoch_restarted"],
                "verdict": evidence["verdict"],
                "paper_trading_authorized": evidence["paper_trading_authorized"],
                "live_trading_authorized": evidence["live_trading_authorized"],
            },
            sort_keys=True,
            indent=2,
        ),
        "```",
        "",
        f"Next strategy-facing action: {evidence['next_strategy_action']}.",
        "",
    ])
    (output_dir / "report.md").write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = build_evidence()
    write_outputs(args.output_dir, evidence)
    print(json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
