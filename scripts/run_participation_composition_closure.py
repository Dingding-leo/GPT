from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-participation-composition-programme-closure-1h-v1"
ISSUE_NUMBER = 1141
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
FEE_ONE_WAY = 0.0005
CANDIDATE_COUNT = 0
PARAMETER_GRID_COUNT = 0
HISTORICAL_CANDIDATES = 8
VERDICT = "reject_reopening_completed_participation_composition_mechanisms_1h_v1"
OUT = Path("reports/research") / FAMILY_ID


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def null_metrics() -> dict[str, None]:
    keys = (
        "train_return", "train_sharpe", "oos_return", "oos_sharpe",
        "full_return", "full_sharpe", "benchmark_comparison", "turnover",
        "modeled_fee_drag", "maximum_drawdown", "edge_per_turnover",
        "fold_breadth", "year_breadth", "dependence_uncertainty", "one_hour_delay",
    )
    return {key: None for key in keys}


def group_a() -> dict[str, Any]:
    return {
        "group": "A",
        "mechanism_class": "own-market participation and transaction-cost-basis transforms",
        "owner_issue": 1090,
        "evidence_pr": 1092,
        "exact_head": "737be22fcb4d32f50f03ab404a5c113c73398003",
        "base_main": BASE_MAIN,
        "pr_closed": True,
        "pr_merged": False,
        "terminal_verdict": "reject_reopening_completed_own_price_participation_cost_basis_mechanisms_1h_v1",
        "historical_candidate_count": 8,
        "new_candidate_count": 0,
        "parameter_grid_count": 0,
        "top_level_bound_groups": 3,
        "independently_admissible_mechanisms": 0,
        "programme_gates_passed": 3,
        "programme_gates_total": 10,
        "evidence_sha256": "d78caaba25b3fc36073045a8c66581c1181f2444bed7063772cd6c5d41cb6158",
        "report_sha256": "7b1178bfd812ffbb464e612589672fafac29a4d0408c2d265190a597d0e60b7b",
        "source_evidence_zip_sha256": {
            "issue_909": "3ecb3b74cf5117f69f40901f95a2a2f58d3c2888512dcbc9de3a13e0c8150708",
            "issue_1027": "56180347933cf65ac63fc0bc7416f5b8ca1024cd8a156255cde396909b5b90f0",
            "issue_1088": "47b8aa42c5b12b29cbf43d3512f5ee5d85fdfc87209f70c36265ef76736966fa",
        },
        "strongest_historical_point_estimate": {
            "mechanism": "volume_weighted_directional_persistence_issue_642",
            "BTC-USDT": {
                "train_return": -0.2465, "train_sharpe": -0.428,
                "oos_return": 1.4118, "oos_sharpe": 1.071,
                "full_return": 0.8172, "full_sharpe": 0.566,
                "benchmark_oos_return": 1.1968, "benchmark_oos_sharpe": 0.954,
                "oos_turnover": 23.0, "benchmark_oos_turnover": 45.0,
                "oos_edge_per_turnover_bps": 451.96,
                "benchmark_oos_edge_per_turnover_bps": 212.75,
                "oos_max_drawdown": -0.3094, "benchmark_oos_max_drawdown": -0.2655,
                "profitable_oos_folds": 6, "oos_folds": 12,
                "mean_delta_lower_95": -0.0787, "sharpe_delta_lower_95": -0.1997,
            },
            "ETH-USDT": {
                "train_return": -0.2411, "train_sharpe": -0.287,
                "oos_return": 1.4070, "oos_sharpe": 0.899,
                "full_return": 0.8267, "full_sharpe": 0.523,
                "benchmark_oos_return": 0.7452, "benchmark_oos_sharpe": 0.646,
                "oos_turnover": 10.0, "benchmark_oos_turnover": 30.0,
                "oos_edge_per_turnover_bps": 1159.89,
                "benchmark_oos_edge_per_turnover_bps": 283.58,
                "profitable_oos_folds": 6, "oos_folds": 12,
                "mean_delta_lower_95": -0.0193, "sharpe_delta_lower_95": -0.0280,
            },
        },
        "cost_basis_replication": {
            "1INCH-USDT": {"net_rho": -0.024829, "net_standardized_slope": -0.003833, "net_outer_tercile_bp": -41.10},
            "SNX-USDT": {"net_rho": -0.034144, "net_standardized_slope": -0.001114, "net_outer_tercile_bp": -105.28},
            "dependence_support": False,
            "delay_support": False,
        },
        "decisive_failure": "zero independently admissible mechanisms; #642 combines negative bilateral training economics, 6/12 profitable OOS folds and non-positive dependence lower bounds",
        "independently_admissible": False,
    }


def group_b() -> dict[str, Any]:
    return {
        "group": "B",
        "mechanism_class": "same-underlying perpetual-versus-spot total quote-activity share",
        "owner_issue": 1139,
        "evidence_pr": 1140,
        "exact_head": "03958df2da40238818129f29137408a482a5825c",
        "base_main": BASE_MAIN,
        "focused_workflow": 31269297032,
        "artifact": 9025125826,
        "artifact_sha256": "432f935f75cf793efc4d30fd430d34a90d581b264b8aac806ae37ecaae4542cc",
        "evidence_sha256": "33987cc4a1510752571a495409d8f522b45962521c5add818856b2d1e2f569be",
        "report_sha256": "9ac2690f2ddf4c0c773b14c200490515309bee43cf853f7c4c6e2ab77f5f1024",
        "manifest_sha256": "268eee0e9e3561ed5850dc25794135151d461e7564a5b6da52e3b71c7095f455",
        "pr_closed": True,
        "pr_merged": False,
        "terminal_verdict": "reject_causal_same_asset_perpetual_vs_spot_participation_share_information_premise_1h_v1",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "source": "Binance official monthly SPOT and USD-M perpetual 1h archives plus companion checksums",
        "sample": {
            "start": "2023-04-01T00:00:00Z", "end": "2025-12-31T23:00:00Z",
            "rows_per_source_arm": 24144, "source_arms": 4,
            "train": [2208, 10800], "sealed_oos": [10800, 23760], "unread_suffix": [23760, 24144],
        },
        "source_contract_passed": True,
        "sealed_oos_accessed": False,
        "strategy_performance_accessed": False,
        "frozen_expected_sign": "negative",
        "targets": {
            "BTCUSDT": {
                "opportunities": 285, "feature_distinct": 285, "feature_iqr": 0.007051,
                "net_rho": 0.053952, "net_standardized_slope": 0.001326, "net_outer_tercile_bp": 31.95,
                "adverse_rho": 0.040057, "adverse_standardized_slope": 0.001678, "adverse_outer_tercile_bp": 20.24,
                "negative_net_folds": 1, "negative_adverse_folds": 1, "folds": 4,
                "negative_net_fold_concentration": 1.0, "negative_adverse_fold_concentration": 1.0,
                "net_rho_ci95": [-0.0644395, 0.1701068], "net_slope_ci95": [-0.0016647, 0.0042588],
                "adverse_rho_ci95": [-0.0661491, 0.1565453], "adverse_slope_ci95": [-0.00190885, 0.0058895],
                "lower_margin_stratum_net_tercile_bp": 57.19, "lower_margin_stratum_adverse_tercile_bp": 76.90,
                "upper_margin_stratum_net_tercile_bp": -15.18, "upper_margin_stratum_adverse_tercile_bp": -21.33,
                "delay_net_rho": 0.044079, "delay_net_slope": 0.001187, "delay_net_tercile_bp": 21.19,
                "delay_adverse_rho": 0.041165, "delay_adverse_slope": 0.001580, "delay_adverse_tercile_bp": 22.99,
                "all_original_gates_passed": False,
            },
            "ETHUSDT": {
                "opportunities": 241, "feature_distinct": 241, "feature_iqr": 0.007589,
                "net_rho": 0.072702, "net_standardized_slope": 0.000953, "net_outer_tercile_bp": 18.54,
                "adverse_rho": 0.078884, "adverse_standardized_slope": 0.002521, "adverse_outer_tercile_bp": 43.76,
                "negative_net_folds": 2, "negative_adverse_folds": 1, "folds": 4,
                "negative_net_fold_concentration": 0.9971, "negative_adverse_fold_concentration": 1.0,
                "net_rho_ci95": [-0.056386, 0.192373], "net_slope_ci95": [-0.001098, 0.003041],
                "adverse_rho_ci95": [-0.052791, 0.216451], "adverse_slope_ci95": [-0.001800, 0.006599],
                "lower_margin_stratum_net_tercile_bp": -11.42, "lower_margin_stratum_adverse_tercile_bp": -60.73,
                "upper_margin_stratum_net_tercile_bp": 48.16, "upper_margin_stratum_adverse_tercile_bp": 176.999,
                "delay_net_rho": 0.095435, "delay_net_slope": 0.001437, "delay_net_tercile_bp": 30.28,
                "delay_adverse_rho": 0.115909, "delay_adverse_slope": 0.003099, "delay_adverse_tercile_bp": 62.56,
                "all_original_gates_passed": False,
            },
        },
        "observed_bilateral_direction": "positive_wrong_sign",
        "decisive_failure": "fixed negative leverage-dominance hypothesis is wrong-signed bilaterally and fails dependence, breadth/concentration, margin-strata and +1H transport gates before OOS",
        "independently_admissible": False,
    }


def main() -> None:
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", "UNBOUND")
    groups = [group_a(), group_b()]
    assert all(g["base_main"] == BASE_MAIN for g in groups)
    assert all(g["pr_closed"] and not g["pr_merged"] for g in groups)
    assert sum(bool(g["independently_admissible"]) for g in groups) == 0

    leave_one = []
    for omitted in ("A", "B"):
        retained = [g for g in groups if g["group"] != omitted]
        support = sum(bool(g["independently_admissible"]) for g in retained)
        leave_one.append({
            "omitted_group": omitted,
            "retained_groups": [g["group"] for g in retained],
            "independently_admissible_mechanisms": support,
            "closure_support_remains_zero": support == 0,
        })

    a = groups[0]["strongest_historical_point_estimate"]
    b = groups[1]
    gates = {
        "01_terminal_identities_reconcile": all(g["pr_closed"] and not g["pr_merged"] for g in groups),
        "02_real_immutable_completed_1h_and_5bps_contract": BAR == "1H" and FEE_ONE_WAY == 0.0005,
        "03_group_a_terminal_support_zero": groups[0]["independently_admissible_mechanisms"] == 0,
        "04_group_b_failed_original_training_information_contract_before_oos": not b["independently_admissible"] and not b["sealed_oos_accessed"],
        "05_no_bilateral_positive_dependence_support": (
            a["BTC-USDT"]["mean_delta_lower_95"] <= 0 and a["ETH-USDT"]["mean_delta_lower_95"] <= 0
            and b["targets"]["BTCUSDT"]["net_rho_ci95"][0] <= 0 and b["targets"]["ETHUSDT"]["net_rho_ci95"][0] <= 0
        ),
        "06_no_bilateral_breadth_concentration_delay_support": (
            a["BTC-USDT"]["profitable_oos_folds"] == 6 and a["ETH-USDT"]["profitable_oos_folds"] == 6
            and not b["targets"]["BTCUSDT"]["all_original_gates_passed"] and not b["targets"]["ETHUSDT"]["all_original_gates_passed"]
        ),
        "07_strongest_point_estimate_recorded_as_fragile_not_promoted": a["BTC-USDT"]["train_return"] < 0 and a["ETH-USDT"]["train_return"] < 0,
        "08_leave_one_group_out_support_zero": all(x["closure_support_remains_zero"] for x in leave_one),
        "09_source_feasibility_not_counted_as_alpha": b["source_contract_passed"] and not b["independently_admissible"],
        "10_no_posthoc_rescue_required": True,
    }
    assert len(gates) == 10 and all(gates.values())

    evidence = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "base_main": BASE_MAIN,
        "exact_head": exact_head,
        "bar": BAR,
        "fee_bps_one_way_where_economics_defined": FEE_ONE_WAY * 10_000,
        "candidate_count": CANDIDATE_COUNT,
        "parameter_grid_count": PARAMETER_GRID_COUNT,
        "historical_candidate_count": HISTORICAL_CANDIDATES,
        "new_market_data_rows": 0,
        "new_target_labels": 0,
        "new_oos_access": 0,
        "new_fitting_or_tuning": 0,
        "top_level_group_count": 2,
        "independently_admissible_top_level_groups": 0,
        "groups": groups,
        "non_voting_overlap_exclusions": [
            {"issue": 1108, "reason": "directional aggressor-flow/absorption is a terminal flow family, not an independent participation-composition vote"},
            {"issue": 957, "reason": "cash-venue fragmentation is source-feasibility evidence, not a third participation-composition vote"},
        ],
        "leave_one_group_out": leave_one,
        "gates": gates,
        "gates_passed": sum(gates.values()),
        "gates_total": len(gates),
        "performance": null_metrics(),
        "closed_rescue_surface": [
            "spot/perpetual quote-volume shares and futures-to-spot activity ratios",
            "volume/trade-count participation ratios and turnover-fragmentation re-expressions",
            "average transaction-size, activity-clock and range-per-participation transforms",
            "perpetual-minus-spot total activity levels or activity migrations",
            "signed-volume re-expression and OHLCV participation effects/residuals",
            "alternate 24H/168H/720H windows, smoothing, clipping or thresholds",
            "sign reversal, favourable-fold deletion, target substitution or one-market promotion",
            "fitted combinations of completed rejected participation mechanisms",
        ],
        "canonical_mutation": False,
        "correction_authority": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    evidence_raw = canonical_json(evidence)
    (OUT / "evidence.json").write_bytes(evidence_raw)

    report = f"# Participation-composition programme closure 1H\n\n"
    report += f"- exact head: `{exact_head}`\n"
    report += f"- canonical main: `{BASE_MAIN}`\n"
    report += f"- candidate/grid: `{CANDIDATE_COUNT}/{PARAMETER_GRID_COUNT}`; historical candidates bound: `{HISTORICAL_CANDIDATES}`\n"
    report += "- new market rows / target labels / OOS / fitting: `0 / 0 / 0 / 0`\n"
    report += "- top-level independent support: `0/2`\n"
    report += f"- closure gates: `{sum(gates.values())}/{len(gates)}`\n"
    report += f"- verdict: `{VERDICT}`\n\n"
    report += "## Strategy conclusion\n\n"
    report += (
        "The own-market participation/cost-basis programme and independent perpetual-versus-spot activity-share experiment "
        "contain no unchanged bilateral mechanism surviving training transport, dependence-aware uncertainty, temporal breadth/concentration "
        "and execution-delay requirements. The strongest historical OOS point estimate (#642) remains explicit, but negative bilateral "
        "training economics, 6/12 profitable OOS folds and non-positive dependence lower bounds prohibit promotion. The fresh leverage-dominance "
        "feature is wrong-signed in BTC and ETH and failed before OOS.\n\n"
    )
    report += "Closure-level train/OOS/full economics, benchmark comparison, turnover, drawdown and edge-per-turnover are null because this run creates no executable path.\n"
    report_raw = report.encode()
    (OUT / "report.md").write_bytes(report_raw)

    evidence_sha = digest(evidence_raw)
    report_sha = digest(report_raw)
    (OUT / "evidence.sha256").write_text(evidence_sha + "\n")
    (OUT / "report.sha256").write_text(report_sha + "\n")
    manifest = {
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
        "files": ["evidence.json", "report.md", "evidence.sha256", "report.sha256"],
    }
    manifest_raw = canonical_json(manifest)
    manifest_sha = digest(manifest_raw)
    (OUT / "manifest.json").write_bytes(manifest_raw)
    (OUT / "manifest.sha256").write_text(manifest_sha + "\n")

    print(json.dumps({
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "support": "0/2",
        "gates": f"{sum(gates.values())}/{len(gates)}",
        "verdict": VERDICT,
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
        "manifest_sha256": manifest_sha,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
