from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-forward-implied-volatility-regime-family-closure-1h-v1"
VERDICT = "reject_causal_forward_implied_volatility_regime_family"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
EVALUATED_AT_UTC = "2026-08-01T22:25:00Z"


def source_records() -> list[dict[str, Any]]:
    return [
        {
            "group_id": "direct_public_dvol_source_contract",
            "source_issue": 914,
            "source_pull_request": 916,
            "exact_evidence_head": "8dde5f71876a0062d1bab5d2f03471f207687ca0",
            "focused_workflow_run": 30719081752,
            "artifact_id": 8824279802,
            "artifact_sha256": (
                "8481aa7d4fe72bb3254c430e009b6d15e91274afea503a08f19a60b39330d454"
            ),
            "evidence_sha256": (
                "a92cab98833e9b98e08f12317856eeb06760dce1e127754d5040ac99c0c46d23"
            ),
            "fixed_interval": "2021-04-01T00:00:00Z/2025-12-31T23:00:00Z",
            "rows_per_arm": 41664,
            "arms": {
                "BTC": {
                    "normalized_dataset_sha256": (
                        "e50b9a5c5195ae58542eb4b916694646094675d1b359e36990f9821f95dcb06e"
                    )
                },
                "ETH": {
                    "normalized_dataset_sha256": (
                        "66630a58385e9fdece6be3f22e09325a753a912a1f04cbd2352e933165355e79"
                    )
                },
            },
            "source_valid": True,
            "performance_accessed": False,
            "economic_support": False,
            "support_classification": "source_feasibility_only",
        },
        {
            "group_id": "lagged_dvol_slow_regime_e2160_veto",
            "source_issue": 917,
            "source_pull_request": 918,
            "exact_evidence_head": "24f58bbc978f108770a6b897af0930f1f42aa06b",
            "focused_workflow_run": 30720485693,
            "artifact_id": 8824768606,
            "artifact_sha256": (
                "cfea062e12961bb39d71f06d1abc1ddd0dfd6a57109c050cf67334021bb13475"
            ),
            "evidence_sha256": (
                "9ebcda2aa5af3690a44609e4b5f9ce481dd7224ecc55e711929879283511aeea"
            ),
            "candidate_count": 2,
            "parameter_grid_count": 0,
            "modeled_fee_bps_one_way": 5.0,
            "training_interval": "2021-07-01T00:00:00Z/2023-12-31T23:00:00Z",
            "sealed_oos_interval": "2024-01-01T00:00:00Z/2025-12-31T23:00:00Z",
            "source_valid": True,
            "training_gate_passed": False,
            "oos_accessed": False,
            "full_sample_accessed": False,
            "bootstrap_draws": 0,
            "markets": {
                "BTC-USDT": {
                    "veto_decisions": 169,
                    "veto_quarter_count": 9,
                    "reauthorization_decisions": 10,
                    "candidate": {
                        "net_return": -0.16175973489066842,
                        "annualized_sharpe": -0.10508490647130307,
                        "maximum_drawdown": -0.5064226758160371,
                        "one_way_turnover": 40.0,
                        "edge_per_turnover_bps": -40.43993372266711,
                    },
                    "e2160": {
                        "net_return": -0.008132421258053135,
                        "annualized_sharpe": 0.17079860594686577,
                        "maximum_drawdown": -0.5834049090260867,
                        "one_way_turnover": 46.0,
                        "edge_per_turnover_bps": -1.7679176647941597,
                    },
                    "candidate_positive": False,
                    "candidate_e2160_return_superior": False,
                    "candidate_e2160_sharpe_superior": False,
                    "edge_per_turnover_positive": False,
                    "temporal_support_passed": False,
                },
                "ETH-USDT": {
                    "veto_decisions": 178,
                    "veto_quarter_count": 8,
                    "reauthorization_decisions": 9,
                    "candidate": {
                        "net_return": -0.15508420587052685,
                        "annualized_sharpe": -0.01530527094708661,
                        "maximum_drawdown": -0.3942608410899687,
                        "one_way_turnover": 44.0,
                        "edge_per_turnover_bps": -35.24641042511974,
                    },
                    "e2160": {
                        "net_return": -0.26683569592715606,
                        "annualized_sharpe": -0.05199369079676824,
                        "maximum_drawdown": -0.5779189969362742,
                        "one_way_turnover": 40.0,
                        "edge_per_turnover_bps": -66.70892398178901,
                    },
                    "candidate_positive": False,
                    "candidate_e2160_return_superior": True,
                    "candidate_e2160_sharpe_superior": True,
                    "edge_per_turnover_positive": False,
                    "temporal_support_passed": False,
                },
            },
            "oos_metrics": None,
            "full_sample_metrics": None,
            "fold_breadth": None,
            "calendar_year_breadth": None,
            "dependence_aware_uncertainty": None,
            "one_hour_delay": None,
            "economic_support": False,
            "support_classification": "active_but_bilaterally_negative_training_economics",
            "source_verdict": (
                "reject_causal_lagged_dvol_slow_regime_veto_e2160_1h_v1"
            ),
        },
    ]


def build_evidence(tested_head: str) -> dict[str, Any]:
    records = source_records()
    source_valid_groups = sum(bool(record["source_valid"]) for record in records)
    economic_groups = sum(bool(record["economic_support"]) for record in records)
    strategy = records[1]
    markets = strategy["markets"]
    bilateral_positive = all(market["candidate_positive"] for market in markets.values())
    bilateral_return_superior = all(
        market["candidate_e2160_return_superior"] for market in markets.values()
    )
    bilateral_sharpe_superior = all(
        market["candidate_e2160_sharpe_superior"] for market in markets.values()
    )
    temporal_support = all(market["temporal_support_passed"] for market in markets.values())
    family_gates = {
        "bound_source_identities_exact": source_valid_groups == 2,
        "no_new_provider_or_target_data_accessed": True,
        "source_feasibility_separated_from_economic_support": True,
        "bilateral_positive_candidate_economics": bilateral_positive,
        "bilateral_e2160_return_superiority": bilateral_return_superior,
        "bilateral_e2160_sharpe_superiority": bilateral_sharpe_superior,
        "bilateral_temporal_support": temporal_support,
        "uncertainty_fold_year_delay_support": False,
        "leave_one_group_out_economic_support": False,
        "no_post_hoc_market_or_parameter_rescue": True,
    }
    leave_one_out = {
        "omit_direct_public_dvol_source_contract": {
            "remaining_groups": 1,
            "remaining_economically_supportive_groups": 0,
            "support_nonzero": False,
        },
        "omit_lagged_dvol_slow_regime_e2160_veto": {
            "remaining_groups": 1,
            "remaining_economically_supportive_groups": 0,
            "support_nonzero": False,
        },
    }
    return {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "classification": "completed_evidence_strategy_family_closure",
        "tested_head": tested_head,
        "repository_main": REPOSITORY_MAIN,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "bar": "1H",
        "modeled_fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_oos_consumed": 0,
        "performance_recomputed": False,
        "synthetic_market_data_used": False,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral_or_long_short": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "accounts_or_orders": False,
        "source_records": records,
        "architecture_counts": {
            "architecture_groups": len(records),
            "source_valid_groups": source_valid_groups,
            "economically_supportive_groups": economic_groups,
            "bilateral_positive_return_groups": int(bilateral_positive),
            "bilateral_e2160_return_superior_groups": int(bilateral_return_superior),
            "bilateral_e2160_sharpe_superior_groups": int(bilateral_sharpe_superior),
            "temporal_support_groups": int(temporal_support),
            "uncertainty_fold_year_delay_support_groups": 0,
        },
        "family_gates": family_gates,
        "family_gate_pass_count": sum(family_gates.values()),
        "family_gate_count": len(family_gates),
        "leave_one_group_out": leave_one_out,
        "highest_value_failure_mechanism": {
            "classification": "fixed_sign_forward_iv_veto_removed_or_failed_to_create_edge",
            "diagnosis": (
                "The provider-defined DVOL channel was source-valid and active, but the frozen "
                "slow rising-DVOL risk-off rule failed the bilateral training gate. It removed "
                "profitable BTC E2160 exposure, while ETH improved a weak benchmark yet remained "
                "negative with negative edge per turnover. Reauthorisation was sparse in both "
                "arms, and no sealed OOS evidence was authorised."
            ),
        },
        "closed_rescue_paths": [
            "alternate recent or prior DVOL windows and lags",
            "level, change, ratio, z-score or quantile relabeling of the same slow state",
            "post-result sign reversal",
            "thresholds, smoothing or hysteresis",
            "hard-veto versus fractional-size variants of the same state",
            "BTC-only or ETH-only promotion",
            "favourable-period, fold or market filtering",
        ],
        "correction_applied": False,
        "canonical_strategy_changed": False,
        "prospective_shadow_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
        "next_architecture_nomination": {
            "family_id": "causal-onchain-fee-pressure-source-contract-1h-v1",
            "classification": "source_contract_first_orthogonal_exogenous_information",
            "fixed_arms": ["BTC fee pressure -> BTC-USDT", "ETH fee pressure -> ETH-USDT"],
            "provider_boundary": (
                "credential-free Coin Metrics Community direct hourly FeeTotUSD only"
            ),
            "first_gate": (
                "prove exact public 1H availability, complete immutable UTC grids, causal "
                "publication timing, stable prefix replay and bilateral metric semantics before "
                "defining an executable rule or accessing target returns"
            ),
            "candidate_count_before_source_gate": 0,
            "performance_seen": False,
            "oos_accessed": False,
            "reason_materially_orthogonal": (
                "on-chain settlement-fee pressure measures blockspace demand rather than spot "
                "price, aggregate implied-volatility level, funding, basis or candle activity"
            ),
        },
    }


def canonical_payload(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"


def write_report(output_dir: Path, evidence: dict[str, Any]) -> None:
    strategy = evidence["source_records"][1]
    counts = evidence["architecture_counts"]
    lines = [
        "# Aggregate forward-IV regime family closure",
        "",
        f"- Family: `{evidence['family_id']}`",
        f"- Exact tested head: `{evidence['tested_head']}`",
        f"- Architecture groups: `{counts['architecture_groups']}`",
        f"- New candidates/data/OOS: `0 / 0 / 0`",
        f"- Verdict: `{evidence['verdict']}`",
        "",
        "## Architecture support matrix",
        "",
        "| Group | Source valid | Economics accessed | Bilateral support |",
        "|---|---:|---:|---:|",
        "| Direct public DVOL source contract | true | false | source only |",
        "| Lagged DVOL slow-regime E2160 veto | true | training only | false |",
        "",
        "## Frozen training economics",
        "",
        (
            "| Market | Candidate net / Sharpe | E2160 net / Sharpe | "
            "Candidate / E2160 MDD | Candidate / E2160 turnover | "
            "Candidate / E2160 edge/turnover |"
        ),
        "|---|---:|---:|---:|---:|---:|",
    ]
    for market_name, market in strategy["markets"].items():
        candidate = market["candidate"]
        benchmark = market["e2160"]
        lines.append(
            f"| {market_name} | {candidate['net_return']:.5%} / "
            f"{candidate['annualized_sharpe']:+.5f} | {benchmark['net_return']:.5%} / "
            f"{benchmark['annualized_sharpe']:+.5f} | "
            f"{candidate['maximum_drawdown']:.5%} / {benchmark['maximum_drawdown']:.5%} | "
            f"{candidate['one_way_turnover']:.0f} / {benchmark['one_way_turnover']:.0f} | "
            f"{candidate['edge_per_turnover_bps']:+.5f} / "
            f"{benchmark['edge_per_turnover_bps']:+.5f} bp |"
        )
    lines.extend(
        [
            "",
            "OOS and full-sample economics, fold/year breadth, dependence-aware uncertainty and "
            "one-hour-delay results remain `null`, not zero, because the bilateral training gate "
            "failed before sealed OOS access.",
            "",
            "## Architecture counts",
            "",
            "```json",
            json.dumps(counts, sort_keys=True, indent=2),
            "```",
            "",
            "## Family gates",
            "",
            "```json",
            json.dumps(evidence["family_gates"], sort_keys=True, indent=2),
            "```",
            "",
            "## Failure mechanism",
            "",
            evidence["highest_value_failure_mechanism"]["diagnosis"],
            "",
            "## Next materially orthogonal architecture",
            "",
            f"`{evidence['next_architecture_nomination']['family_id']}` is nominated "
            "source-contract first. It may not define a candidate or inspect target returns until "
            "the direct public "
            "hourly on-chain source passes bilaterally.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def run(output_dir: Path, tested_head: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_evidence(tested_head)
    payload = canonical_payload(evidence)
    digest = hashlib.sha256(payload).hexdigest()
    (output_dir / "evidence.json").write_bytes(payload)
    (output_dir / "evidence.sha256").write_text(digest + "\n", encoding="utf-8")
    write_report(output_dir, evidence)
    report_digest = hashlib.sha256((output_dir / "report.md").read_bytes()).hexdigest()
    (output_dir / "report.sha256").write_text(report_digest + "\n", encoding="utf-8")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tested-head", default=os.environ.get("EXPECTED_TESTED_SHA", ""))
    args = parser.parse_args()
    if len(args.tested_head) != 40 or any(
        character not in "0123456789abcdef" for character in args.tested_head
    ):
        raise SystemExit("tested head must be an exact lowercase 40-character SHA")
    print(json.dumps(run(args.output_dir, args.tested_head), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
