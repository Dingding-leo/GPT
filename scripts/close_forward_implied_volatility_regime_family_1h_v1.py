from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-forward-implied-volatility-regime-family-closure-1h-v1"
VERDICT = "reject_causal_forward_implied_volatility_regime_family"


def group_records() -> list[dict[str, Any]]:
    return [
        {
            "group": "direct_public_dvol_source_contract",
            "issue": 914,
            "pull_request": 916,
            "family_id": "causal-dvol-regime-adaptive-e2160-sizing-source-contract-1h-v1",
            "tested_head": "8dde5f71876a0062d1bab5d2f03471f207687ca0",
            "workflow_run": 30719081752,
            "artifact_id": 8824279802,
            "artifact_sha256": "8481aa7d4fe72bb3254c430e009b6d15e91274afea503a08f19a60b39330d454",
            "evidence_sha256": "a92cab98833e9b98e08f12317856eeb06760dce1e127754d5040ac99c0c46d23",
            "source_valid": True,
            "markets": ["BTC", "ETH"],
            "rows_per_arm": 41664,
            "performance_accessed": False,
            "oos_accessed": False,
            "candidate_count": 0,
            "training_economics": None,
            "oos_economics": None,
            "full_economics": None,
            "bilateral_positive_return": False,
            "bilateral_e2160_superiority": False,
            "bilateral_positive_edge_per_turnover": False,
            "temporal_support": False,
            "uncertainty_fold_year_delay_support": False,
            "economically_supportive": False,
            "classification": "source_feasibility_only",
        },
        {
            "group": "lagged_dvol_slow_regime_e2160_veto",
            "issue": 917,
            "pull_request": 918,
            "family_id": "causal-lagged-dvol-slow-regime-veto-e2160-1h-v1",
            "tested_head": "24f58bbc978f108770a6b897af0930f1f42aa06b",
            "workflow_run": 30720485693,
            "artifact_id": 8824768606,
            "artifact_sha256": "cfea062e12961bb39d71f06d1abc1ddd0dfd6a57109c050cf67334021bb13475",
            "evidence_sha256": "9ebcda2aa5af3690a44609e4b5f9ce481dd7224ecc55e711929879283511aeea",
            "source_valid": True,
            "markets": ["BTC-USDT", "ETH-USDT"],
            "candidate_count": 2,
            "performance_accessed": True,
            "training_performance_accessed": True,
            "oos_accessed": False,
            "full_sample_accessed": False,
            "training_economics": {
                "BTC-USDT": {
                    "candidate_net_return": -0.1617597,
                    "candidate_sharpe": -0.10508,
                    "e2160_net_return": -0.0081324,
                    "e2160_sharpe": 0.17080,
                    "candidate_max_drawdown": -0.5064227,
                    "e2160_max_drawdown": -0.5834049,
                    "candidate_turnover": 40,
                    "e2160_turnover": 46,
                    "candidate_edge_per_turnover_bps": -40.43993,
                    "e2160_edge_per_turnover_bps": -1.76792,
                    "veto_count": 169,
                    "reauthorization_count": 10,
                },
                "ETH-USDT": {
                    "candidate_net_return": -0.1550842,
                    "candidate_sharpe": -0.01531,
                    "e2160_net_return": -0.2668357,
                    "e2160_sharpe": -0.05199,
                    "candidate_max_drawdown": -0.3942608,
                    "e2160_max_drawdown": -0.5779190,
                    "candidate_turnover": 44,
                    "e2160_turnover": 40,
                    "candidate_edge_per_turnover_bps": -35.24641,
                    "e2160_edge_per_turnover_bps": -66.70892,
                    "veto_count": 178,
                    "reauthorization_count": 9,
                },
            },
            "oos_economics": None,
            "full_economics": None,
            "bilateral_positive_return": False,
            "bilateral_e2160_superiority": False,
            "bilateral_positive_edge_per_turnover": False,
            "temporal_support": False,
            "uncertainty_fold_year_delay_support": False,
            "economically_supportive": False,
            "classification": "training_economic_rejection_before_oos",
        },
    ]


def build_result() -> dict[str, Any]:
    groups = group_records()
    counts = {
        "architecture_group_count": len(groups),
        "source_valid_groups": sum(g["source_valid"] for g in groups),
        "economically_supportive_groups": sum(g["economically_supportive"] for g in groups),
        "bilateral_positive_return_groups": sum(g["bilateral_positive_return"] for g in groups),
        "bilateral_e2160_superior_groups": sum(g["bilateral_e2160_superiority"] for g in groups),
        "temporal_support_groups": sum(g["temporal_support"] for g in groups),
        "uncertainty_fold_year_delay_support_groups": sum(
            g["uncertainty_fold_year_delay_support"] for g in groups
        ),
    }
    gates = [
        {"gate": 1, "name": "exact_source_identities_reproduce", "passed": True},
        {"gate": 2, "name": "no_new_data_oos_parameters_or_series", "passed": True},
        {"gate": 3, "name": "source_feasibility_separated_from_economic_support", "passed": True},
        {"gate": 4, "name": "bilateral_positive_return_and_edge_per_turnover", "passed": False},
        {"gate": 5, "name": "bilateral_e2160_return_and_sharpe_superiority", "passed": False},
        {"gate": 6, "name": "bilateral_activation_reauthorization_and_quarter_breadth", "passed": False},
        {"gate": 7, "name": "published_uncertainty_fold_year_and_delay_support", "passed": False},
        {"gate": 8, "name": "leave_one_group_out_support", "passed": False},
        {"gate": 9, "name": "architecture_level_vote_not_market_vote", "passed": True},
        {"gate": 10, "name": "no_post_result_variant_or_single_market_rescue", "passed": True},
    ]
    loo = {
        "remove_direct_public_dvol_source_contract": 0,
        "remove_lagged_dvol_slow_regime_e2160_veto": 0,
    }
    return {
        "schema_version": "forward-implied-volatility-family-closure-1h-v1",
        "generated_at_utc": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "family_id": FAMILY_ID,
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_oos_consumed": 0,
        "groups": groups,
        "counts": counts,
        "gates": gates,
        "gates_passed": sum(g["passed"] for g in gates),
        "gate_count": len(gates),
        "leave_one_group_out_support": loo,
        "remaining_information_bottleneck": (
            "Provider-defined aggregate forward implied volatility is executable, but the frozen "
            "slow fixed-sign DVOL veto supplies no bilateral positive fee-clearing training edge; "
            "sealed transport evidence therefore remains unavailable."
        ),
        "closed_rescue_paths": [
            "alternate slow DVOL recent/prior windows or lags",
            "level change ratio z-score or quantile relabeling of the same slow state",
            "reversing the risk-off sign after inspection",
            "threshold smoothing hysteresis or fractional sizing",
            "BTC-only or ETH-only promotion",
            "favourable period fold or market filtering",
        ],
        "next_architecture": {
            "family_id": "causal-public-options-term-structure-shape-source-contract-1h-v1",
            "classification": "source_contract_first_materially_distinct_options_information",
            "candidate_count": 0,
            "parameter_grid_count": 0,
            "performance_accessed": False,
            "oos_accessed": False,
            "purpose": (
                "Test only whether a direct credential-free provider-defined historical 1H BTC "
                "and ETH implied-volatility term-structure shape exists; define no strategy rule "
                "or target-return access unless the bilateral source contract passes."
            ),
        },
        "correction_permitted": False,
        "correction_applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
    }


def write_outputs(output_dir: Path, result: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (output_dir / "evidence.json").write_text(payload)
    (output_dir / "evidence.sha256").write_text(digest + "\n")
    c = result["counts"]
    lines = [
        "# Forward implied-volatility regime family closure",
        "",
        f"- Family: `{result['family_id']}`",
        f"- Architecture groups: `{c['architecture_group_count']}`",
        f"- Source-valid groups: `{c['source_valid_groups']}`",
        f"- Economically supportive groups: `{c['economically_supportive_groups']}`",
        f"- Bilateral positive-return groups: `{c['bilateral_positive_return_groups']}`",
        f"- Bilateral E2160-superior groups: `{c['bilateral_e2160_superior_groups']}`",
        f"- Temporal-support groups: `{c['temporal_support_groups']}`",
        f"- Uncertainty/fold/year/delay-support groups: `{c['uncertainty_fold_year_delay_support_groups']}`",
        f"- Gates passed: `{result['gates_passed']}/{result['gate_count']}`",
        f"- Verdict: `{result['verdict']}`",
        "",
        "The direct DVOL history is a valid public 1H source, but source feasibility is not economic support. The sole executable frozen rule failed both training-economic arms, so sealed OOS remained unread and no correction or new epoch is authorised.",
        "",
        "## Training economics",
        "",
        "| Market | Candidate net | Candidate Sharpe | E2160 net | E2160 Sharpe | Candidate MDD | E2160 MDD | Turnover | Edge/turnover |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    economics = result["groups"][1]["training_economics"]
    for market, m in economics.items():
        lines.append(
            f"| {market} | {100*m['candidate_net_return']:+.5f}% | {m['candidate_sharpe']:+.5f} | "
            f"{100*m['e2160_net_return']:+.5f}% | {m['e2160_sharpe']:+.5f} | "
            f"{100*m['candidate_max_drawdown']:+.5f}% | {100*m['e2160_max_drawdown']:+.5f}% | "
            f"{m['candidate_turnover']} / {m['e2160_turnover']} | "
            f"{m['candidate_edge_per_turnover_bps']:+.5f} / {m['e2160_edge_per_turnover_bps']:+.5f} bp |"
        )
    lines.extend(
        [
            "",
            "All OOS and full-sample economic fields remain null. No alternative sign, window, lag, threshold, smoothing, sizing or single-market rescue is permitted.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))
    return digest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = build_result()
    digest = write_outputs(args.output_dir, result)
    print(json.dumps({"evidence_sha256": digest, "verdict": result["verdict"]}, sort_keys=True))


if __name__ == "__main__":
    main()
