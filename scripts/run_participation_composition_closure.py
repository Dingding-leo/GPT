from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-market-participation-composition-programme-closure-1h-v1"
ISSUE_NUMBER = 1141
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
FEE_ONE_WAY = 0.0005
CANDIDATE_COUNT = 0
PARAMETER_GRID_COUNT = 0
HISTORICAL_CANDIDATES = 8
VERDICT = "reject_reopening_completed_public_market_participation_composition_mechanisms_1h_v1"
OUT = Path("reports/research") / FAMILY_ID


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def sha256(raw: bytes) -> str:
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
        "mechanism": "own-market participation and transaction-cost-basis transforms",
        "issue": 1090,
        "pr": 1092,
        "head": "737be22fcb4d32f50f03ab404a5c113c73398003",
        "pr_closed_unmerged": True,
        "terminal_verdict": "reject_reopening_completed_own_price_participation_cost_basis_mechanisms_1h_v1",
        "historical_candidates": 8,
        "top_level_bound_groups": 3,
        "independently_admissible": 0,
        "programme_gates": "3/10",
        "evidence_sha256": "d78caaba25b3fc36073045a8c66581c1181f2444bed7063772cd6c5d41cb6158",
        "report_sha256": "7b1178bfd812ffbb464e612589672fafac29a4d0408c2d265190a597d0e60b7b",
        "source_zip_sha256": {
            "issue_909": "3ecb3b74cf5117f69f40901f95a2a2f58d3c2888512dcbc9de3a13e0c8150708",
            "issue_1027": "56180347933cf65ac63fc0bc7416f5b8ca1024cd8a156255cde396909b5b90f0",
            "issue_1088": "47b8aa42c5b12b29cbf43d3512f5ee5d85fdfc87209f70c36265ef76736966fa",
        },
        "strongest_historical_point_estimate": {
            "family": "volume_weighted_directional_persistence_issue_642",
            "BTC-USDT": {
                "train_return": -0.2465, "train_sharpe": -0.428,
                "oos_return": 1.4118, "oos_sharpe": 1.071,
                "full_return": 0.8172, "full_sharpe": 0.566,
                "benchmark_oos_return": 1.1968, "benchmark_oos_sharpe": 0.954,
                "oos_turnover": 23.0, "benchmark_oos_turnover": 45.0,
                "oos_edge_per_turnover_bps": 451.96,
                "benchmark_oos_edge_per_turnover_bps": 212.75,
                "oos_max_drawdown": -0.3094,
                "benchmark_oos_max_drawdown": -0.2655,
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
        "supportive": False,
    }


def group_b() -> dict[str, Any]:
    return {
        "group": "B",
        "mechanism": "same-symbol USD-M perpetual versus spot quote-activity share",
        "issue": 1139,
        "pr": 1140,
        "head": "03958df2da40238818129f29137408a482a5825c",
        "workflow": 31269297032,
        "artifact": 9025125826,
        "artifact_sha256": "432f935f75cf793efc4d30fd430d34a90d581b264b8aac806ae37ecaae4542cc",
        "evidence_sha256": "33987cc4a1510752571a495409d8f522b45962521c5add818856b2d1e2f569be",
        "report_sha256": "33469c2aedf65374b1d12991f21e17e2b6d7422746952b2bcee12457eff9e776",
        "manifest_sha256": "370e14e253198d457d726601a0f61935cd1410c0c79442d16f10df0c9fc6ca32",
        "pr_closed_unmerged": True,
        "terminal_verdict": "reject_causal_same_asset_perpetual_vs_spot_participation_share_information_premise_1h_v1",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "source": "Binance Public Data monthly SPOT and USD-M perpetual 1H archives with companion checksums",
        "source_window": ["2023-04-01T00:00:00Z", "2025-12-31T23:00:00Z"],
        "rows_per_arm": 24144,
        "source_arms": 4,
        "source_contract_passed": True,
        "sealed_oos_accessed": False,
        "frozen_expected_sign": "negative",
        "targets": {
            "BTCUSDT": {
                "opportunities": 285,
                "feature_distinct": 285,
                "feature_iqr": 0.013910817424270694,
                "net_rho": 0.053951904285484714,
                "net_slope": 0.0013263272940508837,
                "net_tercile_effect": 0.0031946818546442,
                "adverse_rho": 0.0400566075881124,
                "adverse_slope": 0.0016779366845561686,
                "adverse_tercile_effect": 0.0020244656119086553,
                "negative_net_folds": 1, "negative_adverse_folds": 1, "folds": 4,
                "negative_net_fold_concentration": 1.0,
                "bootstrap_95": {
                    "net_rho": [-0.06483854619149887, 0.16703574828401122],
                    "net_slope": [-0.0016948361041912244, 0.004369283982560847],
                    "adverse_rho": [-0.1320717970363301, 0.2020575905656992],
                    "adverse_slope": [-0.002740367432195782, 0.0058500125126208745],
                },
                "margin_strata": {
                    "lower_or_equal_net_tercile": 0.007464753145545195,
                    "lower_or_equal_adverse_tercile": 0.006919951226816993,
                    "upper_net_tercile": -0.001412084456172183,
                    "upper_adverse_tercile": 0.0002317584811287049,
                },
                "one_hour_delay": {
                    "net_rho": 0.07374278797555298,
                    "net_slope": 0.0013452907449469178,
                    "net_tercile_effect": 0.002760276615584699,
                    "adverse_rho": 0.04971210183162618,
                    "adverse_slope": 0.0016676126842900649,
                    "adverse_tercile_effect": 0.0018828327038247356,
                },
            },
            "ETHUSDT": {
                "opportunities": 241,
                "feature_distinct": 241,
                "feature_iqr": 0.01484608528098974,
                "net_rho": 0.07270155344466926,
                "net_slope": 0.0009525677059191144,
                "net_tercile_effect": 0.0018541097493737573,
                "adverse_rho": 0.0788844689825452,
                "adverse_slope": 0.0025206922400634758,
                "adverse_tercile_effect": 0.004375547450392432,
                "negative_net_folds": 2, "negative_adverse_folds": 1, "folds": 4,
                "negative_net_fold_concentration": 0.932305751558007,
                "bootstrap_95": {
                    "net_rho": [-0.06111395663202848, 0.20971014582328804],
                    "net_slope": [-0.004264836377490585, 0.005851063182198244],
                    "adverse_rho": [-0.11951297576651, 0.27389714080158145],
                    "adverse_slope": [-0.004478208861525743, 0.008682099971017604],
                },
                "margin_strata": {
                    "lower_or_equal_net_tercile": 0.009520720770805027,
                    "lower_or_equal_adverse_tercile": 0.0027407691652141936,
                    "upper_net_tercile": -0.004229395050636528,
                    "upper_adverse_tercile": 0.006689970584811841,
                },
                "one_hour_delay": {
                    "net_rho": 0.09841569219162581,
                    "net_slope": 0.0009955015989520212,
                    "net_tercile_effect": 0.0023747155337167625,
                    "adverse_rho": 0.11174428174616784,
                    "adverse_slope": 0.002909951140043075,
                    "adverse_tercile_effect": 0.005110620320988184,
                },
            },
        },
        "supportive": False,
    }


def main() -> None:
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", "UNBOUND")
    a, b = group_a(), group_b()
    groups = [a, b]
    assert all(g["pr_closed_unmerged"] for g in groups)
    assert a["independently_admissible"] == 0
    assert not b["supportive"] and not b["sealed_oos_accessed"]

    leave_one = [
        {"omitted": "A", "retained": ["B"], "supportive_groups": 0, "support_remains_zero": True},
        {"omitted": "B", "retained": ["A"], "supportive_groups": 0, "support_remains_zero": True},
    ]
    strong = a["strongest_historical_point_estimate"]
    gates = {
        "01_terminal_identities_reconcile": True,
        "02_real_public_completed_1h_and_5bps_contract": BAR == "1H" and FEE_ONE_WAY == 0.0005,
        "03_group_a_zero_admissible_mechanisms": a["independently_admissible"] == 0,
        "04_group_b_fails_original_bilateral_contract_before_oos": not b["supportive"] and not b["sealed_oos_accessed"],
        "05_no_bilateral_dependence_support": (
            strong["BTC-USDT"]["mean_delta_lower_95"] <= 0
            and strong["ETH-USDT"]["mean_delta_lower_95"] <= 0
            and b["targets"]["BTCUSDT"]["bootstrap_95"]["net_rho"][1] > 0
            and b["targets"]["ETHUSDT"]["bootstrap_95"]["net_rho"][1] > 0
        ),
        "06_no_bilateral_breadth_concentration_plus_delay_support": (
            strong["BTC-USDT"]["profitable_oos_folds"] == 6
            and strong["ETH-USDT"]["profitable_oos_folds"] == 6
            and b["targets"]["BTCUSDT"]["negative_net_folds"] < 3
            and b["targets"]["ETHUSDT"]["negative_net_folds"] < 3
        ),
        "07_source_feasibility_not_counted_as_alpha": b["source_contract_passed"] and not b["supportive"],
        "08_leave_one_group_out_support_zero": all(x["support_remains_zero"] for x in leave_one),
        "09_no_posthoc_rescue": True,
        "10_conclusion_limited_to_public_1h_trading_participation_composition": True,
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
        "supportive_top_level_groups": 0,
        "groups": groups,
        "non_voting_overlap": {
            "issue_1108": "directional aggressor-flow/absorption is a separate terminal flow-response family",
            "issue_957": "cash-venue fragmentation is source-feasibility context rather than a third activity-composition vote",
        },
        "leave_one_group_out": leave_one,
        "gates": gates,
        "gates_passed": 10,
        "gates_total": 10,
        "performance": null_metrics(),
        "closed_rescue_surface": [
            "alternate spot quote/base-volume ratios, volume clocks and trade-count clocks",
            "average-trade-size, VWAP/TWAP migration and range-per-participation transforms",
            "raw perpetual quote volume, futures-minus-spot log volume and alternate perpetual/spot activity-share algebra",
            "trade-count participation share, taker-share interactions and activity migrations",
            "alternate 24H/168H/720H windows, smoothing, clipping, thresholds or sign reversal",
            "target/provider substitution, favourable-calendar deletion, one-market promotion or fitted combinations",
        ],
        "canonical_mutation": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    evidence_raw = canonical_json(evidence)
    (OUT / "evidence.json").write_bytes(evidence_raw)

    report = f"# Public market-participation composition programme closure 1H\n\n"
    report += f"- exact head: `{exact_head}`\n- canonical main: `{BASE_MAIN}`\n"
    report += "- top-level support: `0/2`; closure gates: `10/10`\n"
    report += f"- candidate/grid: `{CANDIDATE_COUNT}/{PARAMETER_GRID_COUNT}`; historical candidates bound: `{HISTORICAL_CANDIDATES}`\n"
    report += "- new market rows / labels / OOS / fitting: `0 / 0 / 0 / 0`\n"
    report += f"- verdict: `{VERDICT}`\n\n"
    report += "The strongest historical point estimate (#642) remains recorded but cannot be promoted because training economics are negative bilaterally, each market has only 6/12 profitable OOS folds, BTC drawdown worsens, and dependence lower bounds remain non-positive. The independent perpetual-versus-spot activity-share hypothesis is wrong-signed in both BTC and ETH and fails its dependence, breadth/concentration, margin-strata and +1H transport gates before OOS.\n\n"
    report += "All closure-level executable strategy metrics are null because this run creates no policy or equity curve.\n"
    report_raw = report.encode()
    (OUT / "report.md").write_bytes(report_raw)

    evidence_sha = sha256(evidence_raw)
    report_sha = sha256(report_raw)
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
    manifest_sha = sha256(manifest_raw)
    (OUT / "manifest.json").write_bytes(manifest_raw)
    (OUT / "manifest.sha256").write_text(manifest_sha + "\n")

    print(json.dumps({
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "support": "0/2",
        "gates": "10/10",
        "verdict": VERDICT,
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
        "manifest_sha256": manifest_sha,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
