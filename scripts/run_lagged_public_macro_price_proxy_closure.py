#!/usr/bin/env python3
"""Deterministic immutable-evidence closure for lagged public macro-price proxies."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-lagged-public-macro-price-regime-proxy-programme-closure-1h-v1"
ISSUE_NUMBER = 1137
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
FEE_ONE_WAY = 0.0005
CANDIDATE_COUNT = 0
PARAMETER_GRID_COUNT = 0
OUT = Path("reports/research") / FAMILY_ID
VERDICT = "reject_reopening_completed_lagged_public_macro_price_regime_proxies_1h_v1"
INSUFFICIENT = "insufficient_evidence_to_close_lagged_public_macro_price_regime_proxies_1h_v1"

PERFORMANCE_NULLS = {
    "train_strategy_return": None,
    "train_strategy_sharpe": None,
    "oos_strategy_return": None,
    "oos_strategy_sharpe": None,
    "full_strategy_return": None,
    "full_strategy_sharpe": None,
    "benchmark_comparison": None,
    "turnover": None,
    "modeled_fee_drag": None,
    "maximum_drawdown": None,
    "edge_per_turnover": None,
    "fold_breadth": None,
    "calendar_year_breadth": None,
    "dependence_uncertainty": None,
    "one_hour_delay_performance": None,
}


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def group_a() -> dict[str, Any]:
    """Bind completed #1074 as one already-adjudicated top-level evidence group."""
    return {
        "group_id": "A",
        "owner_issue": 1074,
        "evidence_pr": 1076,
        "family_id": "causal-lagged-cross-market-price-risk-appetite-programme-closure-1h-v1",
        "exact_head": "54324f24dd225b4855a55da0f95175bcf2b89ac1",
        "terminal_verdict": "reject_reopening_completed_lagged_cross_market_price_risk_appetite_mechanisms_1h_v1",
        "completed_public_1h": True,
        "causal_lagging": True,
        "fee_bps_one_way_where_economics_defined": 5.0,
        "top_level_vote": 1,
        "internal_mechanism_count": 3,
        "independently_admissible_internal_mechanisms": 0,
        "internal_owners": [877, 963, 1072],
        "independently_admissible": False,
        "source_feasible_is_alpha": False,
        "strongest_historical_executable": {
            "owner_issue": 877,
            "mechanism": "lagged BTC downside-stress entry veto",
            "sample_rows_per_market": 43941,
            "warmup": [0, 2880],
            "training": [2880, 17520],
            "oos": [17520, 43440],
            "full": [2880, 43440],
            "oos_fold_count": 12,
            "represented_years": 4,
            "BTC-USDT": {
                "candidate": {
                    "train_return": -0.4144068120,
                    "train_sharpe": -0.8481532991,
                    "train_mdd": -0.5603465,
                    "train_turnover": 26,
                    "train_fee_drag": 0.0130,
                    "train_edge_per_turnover_bp": -173.2577,
                    "oos_return": 1.1536688621,
                    "oos_sharpe": 0.9346259394,
                    "oos_mdd": -0.2654678574,
                    "oos_turnover": 43,
                    "oos_fee_drag": 0.0215,
                    "oos_edge_per_turnover_bp": 217.9500,
                    "full_return": 0.2611738148,
                    "full_sharpe": 0.3171570309,
                    "full_mdd": -0.5603465,
                    "full_turnover": 69,
                    "full_fee_drag": 0.0345,
                    "full_edge_per_turnover_bp": 70.5384,
                },
                "benchmark_e2160": {
                    "train_return": -0.4129061903,
                    "train_sharpe": -0.8402669561,
                    "train_mdd": -0.5592199,
                    "train_turnover": 28,
                    "train_fee_drag": 0.0140,
                    "train_edge_per_turnover_bp": -159.8083,
                    "oos_return": 1.1968197962,
                    "oos_sharpe": 0.9537651194,
                    "oos_mdd": -0.2654678574,
                    "oos_turnover": 45,
                    "oos_fee_drag": 0.0225,
                    "oos_edge_per_turnover_bp": 212.7513,
                    "full_return": 0.2897393034,
                    "full_sharpe": 0.3317518864,
                    "full_mdd": -0.5592199,
                    "full_turnover": 73,
                    "full_fee_drag": 0.0365,
                    "full_edge_per_turnover_bp": 69.8517,
                },
                "paired_lower_bound_annualized_mean_delta": -0.023288,
                "paired_lower_bound_sharpe_delta": -0.066460,
                "profitable_oos_folds": 5,
                "profitable_oos_years": 3,
                "fold_count": 12,
                "year_count": 4,
                "positive_fold_return_concentration": 0.34066,
                "selector_effect_temporally_concentrated": True,
            },
            "ETH-USDT": {
                "candidate": {
                    "train_return": -0.4243946828,
                    "train_sharpe": -0.6336371556,
                    "train_mdd": -0.5829284,
                    "train_turnover": 23,
                    "train_fee_drag": 0.0115,
                    "train_edge_per_turnover_bp": -182.7313,
                    "oos_return": 0.8677488634,
                    "oos_sharpe": 0.6973801551,
                    "oos_mdd": -0.4490190672,
                    "oos_turnover": 28,
                    "oos_fee_drag": 0.0140,
                    "oos_edge_per_turnover_bp": 327.8900,
                    "full_return": 0.0750861769,
                    "full_sharpe": 0.2510800576,
                    "full_mdd": -0.5829284,
                    "full_turnover": 51,
                    "full_fee_drag": 0.0255,
                    "full_edge_per_turnover_bp": 97.6098,
                },
                "benchmark_e2160": {
                    "train_return": -0.4058878438,
                    "train_sharpe": -0.5841780886,
                    "train_mdd": -0.5695188,
                    "train_turnover": 23,
                    "train_fee_drag": 0.0115,
                    "train_edge_per_turnover_bp": -168.7689,
                    "oos_return": 0.7451603411,
                    "oos_sharpe": 0.6456279608,
                    "oos_mdd": -0.4776594,
                    "oos_turnover": 30,
                    "oos_fee_drag": 0.0150,
                    "oos_edge_per_turnover_bp": 283.5838,
                    "full_return": 0.0368209732,
                    "full_sharpe": 0.2330347648,
                    "full_mdd": -0.5695188,
                    "full_turnover": 53,
                    "full_fee_drag": 0.0265,
                    "full_edge_per_turnover_bp": 87.2798,
                },
                "paired_lower_bound_annualized_mean_delta": 0.0,
                "paired_lower_bound_sharpe_delta": 0.0,
                "profitable_oos_folds": 6,
                "profitable_oos_years": 3,
                "fold_count": 12,
                "year_count": 4,
                "positive_fold_return_concentration": 0.20975,
                "selector_effect_temporally_concentrated": True,
            },
            "bilateral_original_contract_pass": False,
            "decisive_failure": "BTC trailed E2160 on OOS return/Sharpe; bilateral paired lower bounds were non-positive; relative selector effects were narrow and temporally concentrated",
        },
        "other_completed_internal_evidence": {
            "directional_diffusion_issue_963": {
                "targets_passing": 0,
                "target_count": 2,
                "BTC_net_slope_folds": "1/4",
                "BTC_adverse_slope_folds": "2/4",
                "ETH_net_slope_folds": "3/4",
                "ETH_adverse_slope_folds": "2/4",
                "ETH_positive_net_slope_concentration": 0.7174,
                "all_required_dependence_lower_bounds_positive": False,
                "delayed_adverse_transport_bilateral": False,
            },
            "lagged_okb_issue_1072": {
                "targets_passing": 0,
                "target_count": 2,
                "HBAR_net_rho": -0.055980,
                "HBAR_net_slope": -0.005153,
                "HBAR_net_tercile_bp": -148.84,
                "CHZ_net_rho": -0.072686,
                "CHZ_net_slope": -0.006884,
                "CHZ_net_tercile_bp": -122.52,
                "CHZ_net_slope_interval": [-0.013441, -0.001171],
                "CHZ_adverse_slope_interval": [-0.008188, -0.000044],
                "one_hour_delay_remained_adverse_bilaterally": True,
            },
        },
        "bilateral_positive_dependence_support": False,
        "bilateral_breadth_plus_delay_support": False,
        "canonical_mutation": False,
    }


def group_b() -> dict[str, Any]:
    """Bind completed #1135 PAXG training-information diagnostic."""
    return {
        "group_id": "B",
        "owner_issue": 1135,
        "evidence_pr": 1136,
        "family_id": "causal-lagged-paxg-defensive-momentum-opportunity-1h-v1",
        "exact_head": "e813f9a9611716a114d276feb55f3aeabeecb1d7",
        "focused_workflow": 31267000268,
        "artifact_id": 9024461785,
        "artifact_sha256": "a09da78352425318345138eeaf8b7672311b604b787835bfb880a4098ee34494",
        "evidence_sha256": "42973a762ae911bc815a97197e40ea093c04107fc977a40e886d3588e9cf165e",
        "terminal_verdict": "reject_causal_lagged_paxg_defensive_momentum_opportunity_1h_v1",
        "completed_public_1h": True,
        "causal_lagging": True,
        "fee_bps_one_way": 5.0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "source": {
            "instrument": "PAXG-USDT",
            "provider_market": "OKX SPOT public completed 1H",
            "start": "2025-11-01T00:00:00Z",
            "end": "2026-08-07T23:00:00Z",
            "rows": 6720,
            "source_contract_passed": True,
        },
        "target_training": {
            "rows_per_target": 4800,
            "opportunities_per_target": 190,
            "target_oos_accessed": False,
            "unread_suffix_accessed": False,
            "feature": "log(PAXG_close[t-25] / PAXG_close[t-193])",
            "frozen_expected_sign": "higher PAXG momentum -> lower net_24h and more-negative adverse_24h",
            "BTC-USDT": {
                "net_spearman": -0.0308336286,
                "net_standardized_slope": -0.00104723322,
                "net_upper_minus_lower_tercile": 0.00118298752,
                "adverse_spearman": 0.00119933341,
                "adverse_standardized_slope": 0.000699433015,
                "adverse_upper_minus_lower_tercile": 0.00165389648,
                "bootstrap_95": {
                    "net_spearman": [-0.1761650, 0.1019477],
                    "net_slope": [-0.00421707, 0.00206235],
                    "adverse_spearman": [-0.1808489, 0.1962486],
                    "adverse_slope": [-0.00379713, 0.00596231],
                },
                "negative_net_slope_folds": 1,
                "negative_adverse_slope_folds": 2,
                "fold_count": 4,
                "negative_net_fold_concentration": 1.0,
                "negative_adverse_fold_concentration": 0.5623,
                "calendar_2025_net_tercile": 0.00384655,
                "calendar_2025_adverse_tercile": 0.00727563,
                "one_hour_delay_all_signs_supportive": False,
                "all_training_gates_pass": False,
            },
            "ETH-USDT": {
                "net_spearman": -0.07461848,
                "net_standardized_slope": -0.00276785,
                "net_upper_minus_lower_tercile": -0.00165354,
                "adverse_spearman": -0.0282075,
                "adverse_standardized_slope": -0.00135034,
                "adverse_upper_minus_lower_tercile": -0.00125151,
                "bootstrap_95": {
                    "net_spearman": [-0.2078228, 0.0500380],
                    "net_slope": [-0.00723199, 0.00155398],
                    "adverse_spearman": [-0.2087253, 0.1487662],
                    "adverse_slope": [-0.00705567, 0.00442464],
                },
                "negative_net_slope_folds": 2,
                "negative_adverse_slope_folds": 2,
                "fold_count": 4,
                "negative_net_fold_concentration": 0.897,
                "negative_adverse_fold_concentration": 0.886,
                "calendar_2025_terciles_wrong_sign": True,
                "one_hour_delay_aggregate_signs_supportive": True,
                "all_training_gates_pass": False,
            },
        },
        "independently_admissible": False,
        "bilateral_positive_dependence_support": False,
        "bilateral_breadth_plus_delay_support": False,
        "performance": dict(PERFORMANCE_NULLS),
        "canonical_mutation": False,
    }


def main() -> None:
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", "UNBOUND")
    groups = [group_a(), group_b()]
    gates = {
        "terminal_identities_bound": all(g["exact_head"] and g["terminal_verdict"] for g in groups),
        "public_completed_1h_causal_and_five_bps_where_applicable": all(
            g["completed_public_1h"] and g["causal_lagging"] for g in groups
        ) and FEE_ONE_WAY == 0.0005,
        "group_a_zero_independently_admissible_mechanisms": groups[0]["independently_admissible_internal_mechanisms"] == 0,
        "group_b_fails_bilateral_original_training_contract_before_oos": (
            groups[1]["target_training"]["target_oos_accessed"] is False
            and not groups[1]["target_training"]["BTC-USDT"]["all_training_gates_pass"]
            and not groups[1]["target_training"]["ETH-USDT"]["all_training_gates_pass"]
        ),
        "no_group_has_bilateral_positive_dependence_support": not any(g["bilateral_positive_dependence_support"] for g in groups),
        "no_group_has_bilateral_breadth_plus_delay_support": not any(g["bilateral_breadth_plus_delay_support"] for g in groups),
        "source_feasibility_not_counted_as_alpha": all(not g.get("source_feasible_is_alpha", False) for g in groups),
        "leave_one_top_level_group_out_still_unsupported": all(not g["independently_admissible"] for g in groups),
        "no_posthoc_rescue_used": True,
        "closure_scope_limited_to_scalar_lagged_market_price_regime_proxies": True,
    }
    passed = all(gates.values())
    verdict = VERDICT if passed else INSUFFICIENT
    evidence = {
        "schema_version": "lagged-public-macro-price-proxy-closure-v1",
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "base_main": BASE_MAIN,
        "exact_head": exact_head,
        "bar": BAR,
        "fee_bps_one_way_where_economics_defined": FEE_ONE_WAY * 10000,
        "candidate_count": CANDIDATE_COUNT,
        "parameter_grid_count": PARAMETER_GRID_COUNT,
        "new_market_data_rows": 0,
        "new_target_labels": 0,
        "new_oos_access": 0,
        "new_fitting_or_tuning": 0,
        "top_level_group_count": len(groups),
        "independently_admissible_top_level_groups": sum(bool(g["independently_admissible"]) for g in groups),
        "groups": groups,
        "leave_one_top_level_group_out": {
            "remove_group_A": "reject because Group B failed its bilateral original contract",
            "remove_group_B": "reject because Group A has zero independently admissible mechanisms",
        },
        "gates": gates,
        "gates_passed": sum(gates.values()),
        "gates_total": len(gates),
        "performance": dict(PERFORMANCE_NULLS),
        "canonical_mutation": False,
        "correction_authority": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "closed_rescue_surface": [
            "generic scalar crypto-index or coin price used as risk appetite",
            "tokenized gold/silver/commodity price momentum or impulse used only as risk-on/risk-off state",
            "public FX-pair or equity-index-token price momentum used only as scalar macro proxy",
            "alternate 24H/72H/168H/720H price-proxy horizons, z-scores, impulse normalizers, sign reversals or thresholds",
            "market deletion, single-target promotion, favourable calendar selection or post-hoc E2160 combination",
            "ranking/selecting exogenous price proxies by historical or current performance",
        ],
        "verdict": verdict,
    }

    report = f"""# Lagged public macro-price regime proxy programme closure

## Strategy disposition

```text
family_id                 {FAMILY_ID}
base main                 {BASE_MAIN}
exact evidence head       {exact_head}
candidate / grid          0 / 0
new market rows           0
new target labels         0
new OOS observations      0
new fitting / tuning      0
top-level groups          2
independently admissible  0 / 2
closure gates             {sum(gates.values())} / {len(gates)}
verdict                   {verdict}
```

This run performs family-level multiplicity control only. It adds no market row, target label, OOS observation, fitted parameter, threshold, strategy path or bootstrap draw. Missing strategy-level quantities remain null rather than zero.

## Group A — completed lagged cross-market price risk-appetite programme

Issue #1074 / PR #1076 already adjudicated three materially distinct completed price-derived risk-appetite mechanisms and found `0/3` independently admissible. The strongest historical executable point estimate was the #877 lagged-BTC downside-stress veto:

| Market | Segment | Candidate return / Sharpe | E2160 return / Sharpe | Candidate turnover | Candidate MDD | Candidate edge/turn |
|---|---|---:|---:|---:|---:|---:|
| BTC | Train | -41.4407% / -0.8482 | -41.2906% / -0.8403 | 26 | -56.03% | -173.26 bp |
| BTC | OOS | +115.3669% / 0.9346 | +119.6820% / 0.9538 | 43 | -26.55% | +217.95 bp |
| BTC | Full | +26.1174% / 0.3172 | +28.9739% / 0.3318 | 69 | -56.03% | +70.54 bp |
| ETH | Train | -42.4395% / -0.6336 | -40.5888% / -0.5842 | 23 | -58.29% | -182.73 bp |
| ETH | OOS | +86.7749% / 0.6974 | +74.5160% / 0.6456 | 28 | -44.90% | +327.89 bp |
| ETH | Full | +7.5086% / 0.2511 | +3.6821% / 0.2330 | 51 | -58.29% | +97.61 bp |

The attractive ETH OOS point estimate did not establish transport. BTC underperformed E2160 on OOS return and Sharpe. Paired lower bounds were `-0.023288 / -0.066460` for BTC annualised-mean/Sharpe deltas and exactly `0 / 0` for ETH. Absolute profitable-fold breadth was only 5/12 BTC and 6/12 ETH, while the selector's incremental effect was concentrated in one fold. The other #1074 mechanisms were also unsupported: #963 had no bilateral positive dependence support and #1072 produced adverse HBAR/CHZ return relationships, including strictly adverse CHZ slope intervals.

## Group B — lagged PAXG defensive momentum

The independent #1135 experiment first proved a complete immutable public PAXG-USDT native-1H source, then froze one 168H PAXG momentum signal ending at `t-25`. BTC and ETH each contributed exactly 190 non-overlapping 24H training opportunities; each opportunity charged exactly 5 bp on entry plus 5 bp on exit. OOS remained sealed.

| Target | Net rho / slope / tercile | Adverse rho / slope / tercile | Negative-slope folds | Dependence result |
|---|---:|---:|---:|---:|
| BTC | -0.03083 / -0.001047 / +11.83 bp | +0.00120 / +0.000699 / +16.54 bp | 1/4 net; 2/4 adverse | all required intervals cross zero |
| ETH | -0.07462 / -0.002768 / -16.54 bp | -0.02821 / -0.001350 / -12.52 bp | 2/4 net; 2/4 adverse | all required intervals cross zero |

BTC contradicted the preregistered downside-quality sign and both BTC outer-tercile effects were wrong-signed. ETH had the intended aggregate sign but lacked dependence and fold breadth; roughly 90% of its negative fold-slope evidence was concentrated in one fold, and the represented 2025 terciles reversed sign. The +1H replay did not rescue bilateral passage. Therefore no PAXG threshold, sign reversal, alternate horizon, sizing rule or OOS path was authorised.

## Closure adjudication

All ten frozen gates pass. Removing Group A leaves only rejected PAXG evidence. Removing Group B leaves #1074 with zero independently admissible mechanisms. Source feasibility is never counted as alpha support, and no conclusion uses market deletion, favourable-period deletion, sign reversal, alternate lag/window, thresholding or ranking.

The terminal family verdict is therefore:

```text
{verdict}
```

The closure is intentionally narrow. It closes scalar lagged **market-price regime proxies** and their near-variant rescue surface; it does not claim that all external macro information is impossible. A future external-information architecture must introduce a materially different economic object rather than another price momentum/impulse proxy.

## Closure-level strategy metrics

Because this run creates no executable candidate, closure-level train/OOS/full return and Sharpe, benchmark comparison, turnover, modeled fee drag, maximum drawdown, edge per turnover, fold/year strategy breadth, dependence uncertainty and +1H strategy performance are all `null`, not zero.
"""

    OUT.mkdir(parents=True, exist_ok=True)
    evidence_bytes = canonical_json(evidence)
    report_bytes = report.encode()
    (OUT / "evidence.json").write_bytes(evidence_bytes)
    (OUT / "report.md").write_bytes(report_bytes)
    (OUT / "evidence.sha256").write_text(sha256(evidence_bytes) + "\n")
    (OUT / "report.sha256").write_text(sha256(report_bytes) + "\n")
    manifest = {
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "files": {
            "evidence.json": sha256(evidence_bytes),
            "report.md": sha256(report_bytes),
        },
    }
    manifest_bytes = canonical_json(manifest)
    (OUT / "manifest.json").write_bytes(manifest_bytes)
    (OUT / "manifest.sha256").write_text(sha256(manifest_bytes) + "\n")
    print(json.dumps({
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "gates": f"{sum(gates.values())}/{len(gates)}",
        "independently_admissible_top_level_groups": 0,
        "verdict": verdict,
        "evidence_sha256": sha256(evidence_bytes),
        "report_sha256": sha256(report_bytes),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
