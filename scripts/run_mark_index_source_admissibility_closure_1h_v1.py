from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-mark-index-source-admissibility-closure-1h-v1"
VERDICT = "reject_reopening_causal_mark_index_basis_strategy_family_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"

NULL_ECONOMICS = {
    "train_net_return": None,
    "train_sharpe": None,
    "oos_net_return": None,
    "oos_sharpe": None,
    "full_net_return": None,
    "full_sharpe": None,
    "benchmark_net_return": None,
    "benchmark_sharpe": None,
    "turnover": None,
    "modeled_fees": None,
    "edge_per_turnover_bps": None,
    "maximum_drawdown": None,
    "fold_breadth": None,
    "calendar_breadth": None,
    "dependence_aware_uncertainty": None,
    "one_hour_delay": None,
}


def canonical(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(tested_head: str) -> dict[str, Any]:
    groups = [
        {
            "group_id": "continuous_basis_compression_resilience_information",
            "issue": 814,
            "family_id": (
                "coinm-basis-compression-resilience-opportunity-diagnostic-1h-v1"
            ),
            "tested_head": "cb1e3c400e3f0858a9ff3f9f9524c75cd5fc3ed2",
            "artifact_id": 8803573112,
            "artifact_sha256": (
                "94f4a5ecb2e8dd385a72f97073babd6efd3b470cf449d110f960a56a9498e477"
            ),
            "evidence_sha256": (
                "49c24bb514baf79e12503c3b67529d0b06f343340df1964d076f7c07834cf980"
            ),
            "source_feasible": True,
            "candidate_count": 0,
            "executable_candidate_present": False,
            "performance_accessed": False,
            "oos_accessed": False,
            "markets": {
                "BTCUSDT": {
                    "gross_spearman_rho": -0.0497,
                    "gross_spearman_ci_95": [-0.1493, 0.0432],
                    "adverse_spearman_rho": -0.0731,
                    "adverse_spearman_ci_95": [-0.1795, 0.0358],
                    "positive_gross_folds": 3,
                    "positive_adverse_folds": 3,
                    "fold_count": 8,
                    "positive_gross_months": 3,
                    "positive_adverse_months": 3,
                    "month_count": 8,
                    "mean_net_label_return": 0.001173,
                    "embedded_modeled_fees": 0.242,
                    "embedded_turnover": 484,
                },
                "ETHUSDT": {
                    "gross_spearman_rho": 0.0020,
                    "gross_spearman_ci_95": [-0.1031, 0.1051],
                    "adverse_spearman_rho": -0.0171,
                    "adverse_spearman_ci_95": [-0.1412, 0.1061],
                    "positive_gross_folds": 6,
                    "positive_adverse_folds": 4,
                    "fold_count": 8,
                    "positive_gross_months": 6,
                    "positive_adverse_months": 5,
                    "month_count": 8,
                    "mean_net_label_return": 0.000193,
                    "embedded_modeled_fees": 0.242,
                    "embedded_turnover": 484,
                },
            },
            "common_calendar_gross_ci_95": [-0.1108, 0.0569],
            "common_calendar_adverse_ci_95": [-0.1432, 0.0541],
            "relationship_shape": "hump_shaped_non_monotonic",
            "economics": dict(NULL_ECONOMICS),
            "terminal_verdict": (
                "reject_coinm_basis_compression_resilience_information_premise"
            ),
        },
        {
            "group_id": "derivatives_crowding_architecture_family_closure",
            "issue": 870,
            "family_id": "causal-derivatives-crowding-information-family-closure-1h-v1",
            "tested_head": "20a72d547eb4fd6ce28c322d8f522b47f4a55b64",
            "artifact_id": 8817290045,
            "artifact_sha256": (
                "b880de85cbbe0c57c44a4585054a101d2cf0c9f0862fe374705f7d58c2af7d68"
            ),
            "evidence_sha256": (
                "aa1dc08d14edc8051de7ef15858c9227ff6a2dda5bb1301526019658041166ba"
            ),
            "source_records_sha256": (
                "0148c1949acee3dfaf7a2a36bb17c9c4e9340ace83819bb25b84edc679b1596b"
            ),
            "architecture_group_count": 2,
            "supportive_group_count": 0,
            "dimension_pass_counts": {
                "source_complete": 2,
                "bilateral_absolute_fee_clearing": 1,
                "return_and_adverse_information": 0,
                "dependence_support": 0,
                "mechanism_and_latency": 0,
                "temporal_breadth": 1,
            },
            "settled_funding_reset_diagnostic": {
                "BTCUSDT": {
                    "event_count": 20,
                    "positive_labels": 7,
                    "represented_months": 2,
                    "month_count": 3,
                    "mean_net_return": -0.00315561,
                    "delayed_mean_net_return": -0.00344069,
                    "net_effect_ci_bps_95": [-75.5299, 84.6703],
                    "delayed_net_effect_ci_bps_95": [-73.7784, 77.5752],
                },
                "ETHUSDT": {
                    "event_count": 21,
                    "positive_labels": 13,
                    "represented_months": 2,
                    "month_count": 3,
                    "mean_net_return": -0.00005974,
                    "delayed_mean_net_return": -0.00052995,
                    "net_effect_ci_bps_95": [-67.4329, 141.0433],
                    "delayed_net_effect_ci_bps_95": [-93.1111, 146.2585],
                },
            },
            "economics": dict(NULL_ECONOMICS),
            "terminal_verdict": (
                "reject_causal_derivatives_crowding_information_family"
            ),
        },
        {
            "group_id": "direct_public_okx_mark_index_source_feasibility",
            "issue": 941,
            "pull_request": 942,
            "family_id": "causal-same-asset-mark-index-basis-source-contract-1h-v1",
            "tested_head": "774643f02b9309d9ffa872672ee21fe873979859",
            "workflow_run": 30727565948,
            "artifact_id": 8827057115,
            "artifact_sha256": (
                "bdd7174e85ce844fbc549dd85b28395efbb3f429e774acdc552d92d7e2bafd27"
            ),
            "evidence_sha256": (
                "76e7f14033151e578a0f01fe23a512b3fa5f88540add391e5a64aad84f955208"
            ),
            "source_manifest_sha256": (
                "2f0fcff0a43711a909190b28e1b5c279f72dad743b1a46cebbb1989251797dd2"
            ),
            "fixed_arms": [
                "BTC-USDT-SWAP mark",
                "BTC-USDT index",
                "ETH-USDT-SWAP mark",
                "ETH-USDT index",
            ],
            "rows_per_arm": 24144,
            "source_arms_passing": 4,
            "source_arm_count": 4,
            "source_contract_passed": True,
            "candidate_count": 0,
            "parameter_grid_count": 0,
            "feature_defined": False,
            "target_returns_accessed": False,
            "performance_accessed": False,
            "oos_accessed": False,
            "economics": dict(NULL_ECONOMICS),
            "terminal_verdict": (
                "accept_same_asset_mark_index_basis_1h_source_for_separate_"
                "training_only_predeclaration"
            ),
        },
    ]

    gates = {
        "published_evidence_identities_and_hashes_bound": True,
        "completed_basis_architecture_has_positive_absolute_fee_clearing_"
        "economics_bilaterally": False,
        "completed_basis_architecture_has_favourable_bilateral_return_and_"
        "adverse_information": False,
        "completed_basis_architecture_has_strictly_positive_bilateral_"
        "dependence_lower_bounds": False,
        "completed_basis_architecture_passes_temporal_breadth_concentration_"
        "and_delay_bilaterally": False,
        "supportive_architecture_not_terminally_rejected_and_requires_no_"
        "substitution": False,
        "source_only_group_is_not_counted_as_economic_evidence": True,
        "admissibility_survives_removal_of_any_single_evidence_group": False,
    }

    leave_one_out = {
        "remove_continuous_basis_information": {
            "admissible": False,
            "reason": "no completed basis information or economics remains",
        },
        "remove_derivatives_family_closure": {
            "admissible": False,
            "reason": (
                "the remaining basis diagnostic is terminally rejected and all "
                "dependence-aware intervals cross zero"
            ),
        },
        "remove_mark_index_source_feasibility": {
            "admissible": False,
            "reason": (
                "source feasibility is necessary but cannot repair the missing bilateral "
                "economic and dependence support"
            ),
        },
    }

    return {
        "schema_version": "mark-index-source-admissibility-closure-1h-v1",
        "family_id": FAMILY_ID,
        "tested_head": tested_head,
        "repository_main": REPOSITORY_MAIN,
        "generated_at_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "architecture_group_count": len(groups),
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_target_returns": 0,
        "new_oos_consumed": 0,
        "credentials_used": False,
        "private_endpoints_used": False,
        "accounts_or_orders": False,
        "enabled_adapters": False,
        "leverage_or_funds": False,
        "synthetic_data_used": False,
        "non_1h_input_used": False,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral_or_long_short": False,
        "evidence_groups": groups,
        "admissibility_gates": gates,
        "admissibility_gate_pass_count": sum(gates.values()),
        "admissibility_gate_count": len(gates),
        "economically_supportive_group_count": 0,
        "dependence_supported_group_count": 0,
        "bilaterally_promoted_group_count": 0,
        "leave_one_group_out": leave_one_out,
        "leave_one_group_out_admissible_count": sum(
            result["admissible"] for result in leave_one_out.values()
        ),
        "highest_value_failure_mechanism": (
            "The accepted mark/index panel resolves technical source feasibility only. "
            "The pre-existing basis diagnostic found a non-monotonic response with every "
            "bilateral dependence-aware interval crossing zero, and the broader derivatives-"
            "crowding family was already terminally rejected. A clean source cannot create "
            "incremental strategy information after the economic hypothesis has failed."
        ),
        "protocol_conflict": {
            "issue": 944,
            "family_id": (
                "causal-mark-index-basis-compression-confirmed-e2160-entry-1h-v1"
            ),
            "admissible": False,
            "reason": (
                "it is a basis-window/sign/entry-veto rescue inside the consumed "
                "derivatives-crowding family and was declared before this required "
                "admissibility closure completed"
            ),
        },
        "closed_rescue_paths": [
            "mark/index basis level, slope, compression, expansion, volatility, z-score, quantile or persistence transforms",
            "alternate lookbacks, publication lags, smoothers, medians, means, scales, thresholds or hysteresis",
            "hard veto, entry confirmation, exit authority, fractional sizing or state voting based on basis",
            "interaction with E2160, funding, DVOL, spot/index confirmation, target OHLCV or trade-count states",
            "BTC-only or ETH-only promotion, favourable-period filtering, sign reversal or contract/provider substitution",
            "presenting source feasibility as alpha evidence",
        ],
        "training_authorized_correction": {
            "permitted": False,
            "applied": False,
            "canonical_policy_changed": False,
            "observation_epoch_restarted": False,
            "reason": (
                "zero completed basis architecture supplied replicated bilateral, fee-clearing, "
                "dependence-supported economic evidence"
            ),
        },
        "remaining_alpha_blocker": (
            "No materially orthogonal, direct public 1H information source currently has a "
            "predeclared bilateral mechanism with unconsumed training authority."
        ),
        "next_strategy_facing_action": (
            "continue the frozen BTC-USDT and ETH-USDT E2160 prospective shadow; reject issue "
            "#944 without target-return access; nominate no replacement until a materially "
            "orthogonal causal source contract is frozen before feature or performance access"
        ),
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
    }


def write(output_dir: Path, evidence: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = canonical(evidence)
    evidence_sha = digest(payload)
    (output_dir / "evidence.json").write_bytes(payload)
    (output_dir / "evidence.sha256").write_text(evidence_sha + "\n")

    lines = [
        "# Mark-index source admissibility closure",
        "",
        f"- Family: `{FAMILY_ID}`",
        f"- Architecture groups: `{evidence['architecture_group_count']}`",
        f"- Economically supportive groups: `{evidence['economically_supportive_group_count']}`",
        f"- Admissibility gates: `{evidence['admissibility_gate_pass_count']}/{evidence['admissibility_gate_count']}`",
        "- New candidates/data/returns/OOS: `0 / 0 / 0 / 0`",
        f"- Verdict: `{VERDICT}`",
        "",
        "| Group | Source feasible | Executable/economic support | Terminal result |",
        "|---|---:|---:|---|",
        "| Continuous basis compression diagnostic | yes | no | rejected; bilateral dependence intervals cross zero |",
        "| Derivatives-crowding family closure | yes | 0/2 groups | rejected |",
        "| Direct public OKX mark/index source | 4/4 arms | source only | accepted for separate predeclaration only |",
        "",
        "## Strategy-facing conclusion",
        "",
        evidence["highest_value_failure_mechanism"],
        "",
        "Issue #944 is protocol-inadmissible because it reopens a consumed basis-compression "
        "entry-veto rescue before the required family admissibility closure. Its target returns "
        "must remain unread.",
        "",
        "All unavailable candidate train/OOS/full returns, Sharpes, benchmarks, turnover, fees, "
        "drawdown, edge per turnover, folds, calendar breadth and delay results remain null.",
        "",
        "No correction, canonical mutation, observation-epoch restart, paper authority or live "
        "authority is permitted.",
        "",
        f"Evidence SHA-256: `{evidence_sha}`",
        "",
    ]
    report = "\n".join(lines)
    (output_dir / "report.md").write_text(report)
    (output_dir / "report.sha256").write_text(digest(report.encode()) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tested-head", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    evidence = build(args.tested_head)
    write(args.output_dir, evidence)
    print(json.dumps(evidence, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
