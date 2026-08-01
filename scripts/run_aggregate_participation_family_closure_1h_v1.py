from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-aggregate-participation-information-family-closure-1h-v1"
VERDICT = "reject_causal_aggregate_participation_information_family_1h_v1"
REPOSITORY_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
EVALUATED_AT_UTC = "2026-08-01T20:30:00Z"

NULL_ECONOMICS = {
    "train_net_return": None,
    "train_sharpe": None,
    "oos_net_return": None,
    "oos_sharpe": None,
    "full_net_return": None,
    "full_sharpe": None,
    "e2160_train_net_return": None,
    "e2160_train_sharpe": None,
    "e2160_oos_net_return": None,
    "e2160_oos_sharpe": None,
    "e2160_full_net_return": None,
    "e2160_full_sharpe": None,
    "always_long_net_return": None,
    "always_long_sharpe": None,
    "turnover": None,
    "modeled_fees": None,
    "maximum_drawdown": None,
    "edge_per_turnover_bps": None,
    "fold_breadth": None,
    "calendar_year_breadth": None,
    "dependence_aware_uncertainty": None,
    "one_hour_delayed_net_return": None,
    "one_hour_delayed_sharpe": None,
}


def source_records() -> list[dict[str, Any]]:
    return [
        {
            "group_id": "trade_count_clock_endpoint",
            "source_issue": 901,
            "source_pull_request": 903,
            "family_id": "causal-trade-count-clock-endpoint-trend-1h-v1",
            "markets": ["APTUSDT", "LDOUSDT"],
            "exact_evidence_head": "b30a6c414c00111a2b28d1679559440d7556ff2b",
            "focused_workflow_run": 30713014071,
            "artifact_id": 8822483617,
            "artifact_sha256": "cdd7f08c9c18e179faade8562dc59da557167ca87701cefc3c288d874c93645b",
            "evidence_sha256": "e6e72f4705148abd4e920649aa7bee9e64d4f99830cd4df5330ef3758c5dee53",
            "source_objects_verified": 132,
            "source_objects_expected": 132,
            "rows_per_market": 24144,
            "source_valid": True,
            "numerically_variable": True,
            "bilateral_training_support_passed": False,
            "quarter_breadth_passed": False,
            "concentration_control_passed": False,
            "state_transport_support_passed": False,
            "performance_authorized": False,
            "performance_accessed": False,
            "oos_accessed": False,
            "support": {
                "APTUSDT": {
                    "valid_training_decisions": 270,
                    "distinct_lookbacks": 257,
                    "lookback_iqr_hours": 1478.75,
                    "e2160_disagreements": 38,
                    "disagreement_quarters": 2,
                    "direction_counts": {"activity_long_e2160_cash": 19, "activity_cash_e2160_long": 19},
                },
                "LDOUSDT": {
                    "valid_training_decisions": 270,
                    "distinct_lookbacks": 252,
                    "lookback_iqr_hours": 933.25,
                    "e2160_disagreements": 25,
                    "disagreement_quarters": 3,
                    "dominant_direction_fraction": 0.88,
                    "largest_quarter_fraction": 0.52,
                },
            },
            "economics": dict(NULL_ECONOMICS),
            "economics_null_reason": "frozen bilateral training-support gate failed before any return or OOS access",
            "source_verdict": "reject_causal_trade_count_clock_endpoint_trend_1h_v1",
        },
        {
            "group_id": "price_adjusted_average_trade_size",
            "source_issue": 904,
            "source_pull_request": 906,
            "family_id": "causal-price-adjusted-trade-size-confirmed-e2160-entry-1h-v1",
            "markets": ["ATOMUSDT", "NEARUSDT"],
            "exact_evidence_head": "3419837ab3e598c572458c47906da3bd8b0ed52e",
            "focused_workflow_run": 30714627339,
            "artifact_id": 8822945533,
            "artifact_sha256": "2af3dfb591cf534e0f37941c1fdf8bea180ada65beb31a2335e5e75fe9a72be9",
            "evidence_sha256": "14c15d4232f9ed060e2e82caa4b9a5967f90e9c7850295799817c27d44803127",
            "source_objects_verified": 132,
            "source_objects_expected": 132,
            "rows_per_market": 24144,
            "source_valid": True,
            "numerically_variable": True,
            "bilateral_training_support_passed": False,
            "quarter_breadth_passed": False,
            "concentration_control_passed": False,
            "state_transport_support_passed": False,
            "performance_authorized": False,
            "performance_accessed": False,
            "oos_accessed": False,
            "support": {
                "ATOMUSDT": {
                    "valid_training_decisions": 270,
                    "distinct_feature_values": 270,
                    "feature_iqr": 0.210247446,
                    "entry_vetoes": 12,
                    "veto_quarters": 2,
                    "later_authorized_entries": 1,
                },
                "NEARUSDT": {
                    "valid_training_decisions": 270,
                    "distinct_feature_values": 270,
                    "feature_iqr": 0.347586793,
                    "entry_vetoes": 0,
                    "veto_quarters": 0,
                    "later_authorized_entries": 0,
                },
            },
            "economics": dict(NULL_ECONOMICS),
            "economics_null_reason": "frozen bilateral training-support gate failed before any return or OOS access",
            "source_verdict": "reject_causal_price_adjusted_trade_size_confirmed_e2160_entry_1h_v1",
        },
        {
            "group_id": "range_impact_liquidity",
            "source_issue": 907,
            "source_pull_request": 908,
            "family_id": "causal-range-impact-liquidity-confirmed-e2160-entry-1h-v1",
            "markets": ["AVAXUSDT", "FILUSDT"],
            "exact_evidence_head": "ea0a2abe5277da4bb2a41a2e1044fe0d99b95f1a",
            "focused_workflow_run": 30715040930,
            "artifact_id": 8823076798,
            "artifact_sha256": "c0bf18845781e0ba5bce8f4b984773b08e802360349467bb4b3739c0ab466081",
            "evidence_sha256": "d879a9c8965ff9dd4d2e3c75166cb8be981e4d6afe681f9aba7f6f917f1f08fc",
            "source_manifest_sha256": "fb061eb134d3bd6364d9d74a8028b55d627bfb6ca1d96e05763daf0a9deb8162",
            "strategy_bundle_sha256": "25941799b227f10a42c2fe6c856e030dafdd9abb2acc7748becb6a264aa554b2",
            "protocol_sha256": "2a01ab7dd5f881ae9abbb07a1a58a10619dfbc279eb2cd1c50d6089a42f0d78d",
            "source_objects_verified": 132,
            "source_objects_expected": 132,
            "rows_per_market": 24144,
            "source_valid": True,
            "numerically_variable": True,
            "bilateral_training_support_passed": False,
            "quarter_breadth_passed": False,
            "concentration_control_passed": False,
            "state_transport_support_passed": False,
            "performance_authorized": False,
            "performance_accessed": False,
            "oos_accessed": False,
            "support": {
                "AVAXUSDT": {
                    "valid_training_decisions": 270,
                    "distinct_feature_values": 270,
                    "feature_iqr": 0.0001236469947459923,
                    "entry_vetoes": 18,
                    "veto_quarters": 2,
                    "largest_quarter_fraction": 0.5,
                    "later_authorized_entries": 13,
                },
                "FILUSDT": {
                    "valid_training_decisions": 270,
                    "distinct_feature_values": 270,
                    "feature_iqr": 0.00004258388772664318,
                    "entry_vetoes": 0,
                    "veto_quarters": 0,
                    "largest_quarter_fraction": 1.0,
                    "later_authorized_entries": 0,
                },
            },
            "economics": dict(NULL_ECONOMICS),
            "economics_null_reason": "frozen bilateral training-support gate failed before any return or OOS access",
            "source_verdict": "reject_causal_range_impact_liquidity_confirmed_e2160_entry_1h_v1",
        },
    ]


def build_evidence(tested_head: str) -> dict[str, Any]:
    records = source_records()
    supportive = [record for record in records if record["bilateral_training_support_passed"]]
    supportive_markets = sorted({market for record in supportive for market in record["markets"]})
    counts = {
        "architecture_groups": len(records),
        "source_valid_groups": sum(record["source_valid"] for record in records),
        "numerically_variable_groups": sum(record["numerically_variable"] for record in records),
        "bilateral_supportive_groups": len(supportive),
        "temporally_broad_groups": sum(record["quarter_breadth_passed"] for record in records),
        "concentration_controlled_groups": sum(
            record["concentration_control_passed"] for record in records
        ),
        "oos_authorized_groups": sum(record["performance_authorized"] for record in records),
        "economically_supportive_groups": 0,
        "delay_supported_groups": 0,
        "supportive_target_markets": len(supportive_markets),
    }
    family_gates = {
        "all_source_records_exact_and_consistent": counts["source_valid_groups"] == 3,
        "at_least_two_groups_bilateral_training_support": counts["bilateral_supportive_groups"] >= 2,
        "supportive_groups_span_four_markets": counts["supportive_target_markets"] >= 4,
        "at_least_one_supportive_group_oos_authorized": counts["oos_authorized_groups"] >= 1,
        "at_least_one_supportive_group_bilateral_positive_oos": False,
        "at_least_one_supportive_group_bilateral_e2160_superior": False,
        "at_least_one_supportive_group_positive_dependence_bounds": False,
        "at_least_one_supportive_group_breadth_and_delay": False,
        "support_not_dependent_on_dropping_market_or_group": False,
        "leave_one_group_out_support_nonzero": False,
    }
    leave_one_out = {
        record["group_id"]: {
            "omitted_group": record["group_id"],
            "remaining_supportive_groups": sum(
                other["bilateral_training_support_passed"]
                for other in records
                if other["group_id"] != record["group_id"]
            ),
            "support_nonzero": False,
        }
        for record in records
    }
    return {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "classification": "completed_evidence_architecture_family_closure",
        "tested_head": tested_head,
        "repository_main": REPOSITORY_MAIN,
        "evaluated_at_utc": EVALUATED_AT_UTC,
        "bar": "1H",
        "canonical_fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_oos_consumed": 0,
        "performance_recomputed": False,
        "synthetic_data_used": False,
        "cross_sectional_selection": False,
        "pairs_or_spreads": False,
        "market_neutral_or_long_short": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "accounts_or_orders": False,
        "source_records": records,
        "architecture_counts": counts,
        "family_gates": family_gates,
        "family_gate_pass_count": sum(family_gates.values()),
        "family_gate_count": len(family_gates),
        "leave_one_group_out": leave_one_out,
        "highest_value_failure_mechanism": {
            "classification": "variable_features_without_transportable_selector_information",
            "diagnosis": (
                "All three aggregate-participation representations were numerically variable and "
                "source-valid, but decision changes were absent or sparse in one replication arm "
                "and temporally concentrated in the other. No group passed the bilateral "
                "training-only information gate, so no return evidence was authorized. Numerical "
                "feature dispersion therefore did not translate into broad, repeatable selector "
                "information."
            ),
            "profitability_inference_permitted": False,
        },
        "closed_rescue_paths": [
            "alternate trade-count-clock targets, normalisation windows, volume clocks or boundary interpolation",
            "average quote/base trade-size variants, price adjustments or alternate 720H blocks",
            "raw range, ATR, high-low spread or range-per-trade variants",
            "alternate trade-count exponents, rolling means or medians, block lengths or lags",
            "thresholds, smoothing, hysteresis, sign reversal or exit authority",
            "blends or ensembles of the three completed participation states",
            "single-market promotion, market substitution or favourable post-hoc partitions",
        ],
        "correction_permitted": False,
        "correction_applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
        "next_architecture_nomination": {
            "family_id": "causal-options-implied-downside-skew-confirmed-e2160-entry-1h-v1",
            "classification": "source_contract_first_materially_orthogonal_information_experiment",
            "targets": ["BTC-USDT", "ETH-USDT"],
            "rule_boundary": (
                "each target uses only its own lagged E2160 state plus a separately bound, lagged "
                "same-underlying options-implied downside-skew series; independent long/cash sleeves"
            ),
            "first_gate": (
                "prove a credential-free immutable public 1H options history, exact instrument and "
                "expiry identity, quote/trade chronology, causal availability and complete calendar "
                "before defining a feature or accessing target returns"
            ),
            "candidate_count_before_source_gate": 0,
            "performance_seen": False,
            "oos_accessed": False,
            "reason_materially_orthogonal": (
                "option-implied downside pricing is a forward-looking risk-transfer mechanism, not "
                "an algebraic transformation of spot OHLCV or aggregate trade count"
            ),
        },
    }


def canonical_payload(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"


def write_report(output_dir: Path, evidence: dict[str, Any]) -> None:
    counts = evidence["architecture_counts"]
    gates = evidence["family_gates"]
    lines = [
        "# Aggregate-participation information family closure",
        "",
        f"- Family: `{evidence['family_id']}`",
        f"- Exact tested head: `{evidence['tested_head']}`",
        f"- Source groups: `{counts['architecture_groups']}`",
        f"- New candidates/data/OOS: `0 / 0 / 0`",
        f"- Verdict: `{evidence['verdict']}`",
        "",
        "## Architecture matrix",
        "",
        "| Group | Markets | Source valid | Variable | Bilateral support | Breadth | Concentration | OOS authorised | Economics |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for record in evidence["source_records"]:
        lines.append(
            f"| {record['group_id']} | {' / '.join(record['markets'])} | "
            f"{record['source_valid']} | {record['numerically_variable']} | "
            f"{record['bilateral_training_support_passed']} | {record['quarter_breadth_passed']} | "
            f"{record['concentration_control_passed']} | {record['performance_authorized']} | null |"
        )
    lines.extend(
        [
            "",
            "## Counts",
            "",
            "```json",
            json.dumps(counts, sort_keys=True, indent=2),
            "```",
            "",
            "## Frozen family gates",
            "",
            "```json",
            json.dumps(gates, sort_keys=True, indent=2),
            "```",
            "",
            "## Failure mechanism",
            "",
            evidence["highest_value_failure_mechanism"]["diagnosis"],
            "",
            "All performance fields remain `null`, not zero, because every source experiment failed "
            "before performance or sealed OOS access. This closure makes no profitability claim.",
            "",
            "## Disposition",
            "",
            "```text",
            "Correction permitted          false",
            "Correction applied            false",
            "Policy changed                false",
            "Observation epoch restarted   false",
            "Paper trading authorised      false",
            "Live trading authorised       false",
            "```",
            "",
            "## Next materially orthogonal architecture",
            "",
            f"`{evidence['next_architecture_nomination']['family_id']}` is nominated source-contract "
            "first. No candidate or performance access is authorised until immutable public 1H "
            "options chronology and causal availability are proven.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path, tested_head: str) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    evidence = build_evidence(tested_head)
    payload = canonical_payload(evidence)
    digest = hashlib.sha256(payload).hexdigest()
    (output_dir / "evidence.json").write_bytes(payload)
    (output_dir / "evidence.sha256").write_text(digest + "\n")
    write_report(output_dir, evidence)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--tested-head",
        default=os.environ.get("EXPECTED_TESTED_SHA", ""),
    )
    args = parser.parse_args()
    if len(args.tested_head) != 40 or any(c not in "0123456789abcdef" for c in args.tested_head):
        raise SystemExit("tested head must be an exact lowercase 40-character SHA")
    print(json.dumps(run(args.output_dir, args.tested_head), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
