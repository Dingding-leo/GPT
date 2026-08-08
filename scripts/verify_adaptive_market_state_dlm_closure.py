from __future__ import annotations

import json
from pathlib import Path

EVIDENCE = Path(
    "reports/research/adaptive-market-state-dlm-programme-closure-1h-v1/evidence.json"
)
EXPECTED_VERDICT = "reject_queued_adaptive_market_state_dlm_v1_as_superseded_recombination"


def main() -> None:
    evidence = json.loads(EVIDENCE.read_text())

    assert evidence["family_id"] == "causal-adaptive-market-state-dlm-programme-closure-1h-v1"
    assert evidence["repository_main"] == "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
    assert evidence["candidate_count"] == 0
    assert evidence["parameter_grid_count"] == 0
    assert evidence["new_market_data_rows"] == 0
    assert evidence["new_target_returns"] == 0
    assert evidence["new_oos_access"] == 0
    assert evidence["new_fitting_or_tuning"] == 0
    assert evidence["canonical_mutation"] is False
    assert evidence["paper_trading_authorized"] is False
    assert evidence["live_trading_authorized"] is False

    groups = evidence["evidence_groups"]
    assert [group["group"] for group in groups] == ["A", "B", "C1", "C2", "D", "E", "F"]
    assert all(group["independently_supportive"] is False for group in groups)

    pillars = evidence["pillar_adjudication"]
    assert set(pillars) == {
        "target_information",
        "aggregate_state",
        "adaptive_model",
        "decision_turnover",
    }
    assert all(pillar["status"] == "closed_by_completed_evidence" for pillar in pillars.values())
    assert pillars["target_information"]["new_information_object_remaining"] is False
    assert pillars["aggregate_state"]["new_information_object_remaining"] is False
    assert pillars["adaptive_model"]["completed_positive_bilateral_incremental_evidence"] is False
    assert pillars["decision_turnover"]["completed_positive_bilateral_incremental_evidence"] is False

    gates = evidence["retention_gates"]
    assert gates == {
        "g1_materially_new_information_object_remains": False,
        "g2_adaptive_or_decision_component_has_completed_bilateral_positive_incremental_value": False,
        "g3_case_does_not_depend_on_combining_rejected_mechanisms": False,
        "g4_aggregate_state_respects_same_target_causal_boundary": True,
        "g5_leave_one_evidence_group_out_retains_material_independent_rationale": False,
    }
    assert evidence["retention_gates_passed"] == 1
    assert evidence["retention_gate_count"] == 5
    assert set(evidence["leave_one_evidence_group_out"].values()) == {"reject"}
    assert evidence["architecture_independently_justified"] is False

    null_fields = [
        "train_return",
        "train_sharpe",
        "oos_return",
        "oos_sharpe",
        "full_return",
        "full_sharpe",
        "benchmark_comparison",
        "turnover",
        "fee_drag",
        "maximum_drawdown",
        "edge_per_turnover",
        "fold_year_breadth",
        "dependence_uncertainty",
        "execution_delay",
    ]
    assert all(evidence[field] is None for field in null_fields)
    assert evidence["verdict"] == EXPECTED_VERDICT

    # Check the quantitative source facts that directly determine the closure.
    group_a = groups[0]["key_metrics"]
    assert group_a["architecture_median_net_delta_bp_per_hour"] < 0
    assert group_a["architecture_median_net_delta_ci_bp_per_hour"][1] < 0
    assert group_a["architecture_median_sharpe_delta"] < 0
    assert group_a["architecture_median_sharpe_delta_ci"][1] < 0
    assert group_a["positive_architecture_medians_net"] == 0
    assert group_a["positive_architecture_medians_sharpe"] == 0

    group_b = groups[1]["key_metrics"]
    assert group_b["bilateral_benchmark_support_groups"] == 0
    assert group_b["bilateral_dependence_support_groups"] == 0
    assert group_b["bilateral_breadth_delay_support_groups"] == 0

    group_f = groups[-1]["ridge_exception"]
    for target in group_f.values():
        assert target["fit_support"] < target["required_fit_support"]
        assert target["validation_return"] < target["validation_e2160_return"]
        assert target["edge_per_turn_bp"] < 0

    print(EXPECTED_VERDICT)


if __name__ == "__main__":
    main()
