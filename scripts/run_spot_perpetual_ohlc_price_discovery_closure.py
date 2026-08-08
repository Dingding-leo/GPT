from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-same-asset-spot-perpetual-ohlc-price-discovery-programme-closure-1h-v1"
ISSUE_NUMBER = 1147
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
FEE_BPS_ONE_WAY = 5.0
CANDIDATE_COUNT = 0
PARAMETER_GRID_COUNT = 0
VERDICT = "reject_reopening_completed_same_asset_spot_perpetual_ohlc_price_discovery_mechanisms_1h_v1"
OUT = Path("reports/research") / FAMILY_ID


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def null_performance() -> dict[str, None]:
    return {
        "train_return": None,
        "train_sharpe": None,
        "oos_return": None,
        "oos_sharpe": None,
        "full_return": None,
        "full_sharpe": None,
        "benchmark_comparison": None,
        "turnover": None,
        "modeled_fee_drag": None,
        "maximum_drawdown": None,
        "edge_per_turnover": None,
        "calendar_year_strategy_breadth": None,
    }


def range_energy_group() -> dict[str, Any]:
    return {
        "group": "A",
        "mechanism": "same-underlying perpetual-versus-spot intrahour range-energy leadership",
        "issue": 1143,
        "pr": 1144,
        "head": "85065ccf79147ee2977baf4e94ec7e2ed6bbc915",
        "workflow": 31271634634,
        "artifact": 9025803473,
        "artifact_sha256": "ad4daaf65b909a12c74cb39b304245a729b69e426585ab9dd6e51efefa4a72a4",
        "evidence_sha256": "416bd865677d34fd0c405e39277073bd2a55bdfefb3837bbee6f0fd48ff3ea3f",
        "report_sha256": "547a80b6d4316ab81eb5cc09c48dbc7463ee952eea60a3f02cad77a12696feb7",
        "manifest_sha256": "4cc12758b49a891306aaf0a0efd390ed4f260edb715a3cad5db5aa12212cc7c4",
        "public_provider_native_1h": True,
        "fee_bps_one_way": 5.0,
        "source_arms_passed": "4/4",
        "rows_per_source_arm": 24144,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "sealed_oos_accessed": False,
        "expected_sign": "negative",
        "targets": {
            "BTCUSDT": {
                "opportunities": 285,
                "net_rho": -0.0327136910532018,
                "net_slope": -0.0008695675526427083,
                "net_tercile_effect": -0.003679817921300134,
                "adverse_rho": 0.07329238928941806,
                "adverse_slope": 0.0010487580142006139,
                "adverse_tercile_effect": 0.002205821368669125,
                "bootstrap_95": {
                    "net_rho": [-0.1472879916548527, 0.08257908468399891],
                    "net_slope": [-0.003245351424227088, 0.0015492382713364983],
                    "adverse_rho": [-0.05576241570810218, 0.2094538735197378],
                    "adverse_slope": [-0.000995857853307984, 0.0029922175391280444],
                },
                "negative_net_folds": 3,
                "negative_adverse_folds": 0,
                "negative_net_fold_concentration": 0.5993978058015524,
                "margin_strata_pass": False,
                "one_hour_delay_pass": False,
            },
            "ETHUSDT": {
                "opportunities": 241,
                "net_rho": 0.03415949384451837,
                "net_slope": -0.0012521767328466772,
                "net_tercile_effect": 0.005193090471464923,
                "adverse_rho": 0.07470814944173908,
                "adverse_slope": -0.00047884386564334613,
                "adverse_tercile_effect": 0.00032271159899309107,
                "bootstrap_95": {
                    "net_rho": [-0.08253016184735011, 0.1638644271201837],
                    "net_slope": [-0.0049093962342556825, 0.003115880433040682],
                    "adverse_rho": [-0.07470483032839534, 0.22466915542294852],
                    "adverse_slope": [-0.0035355240492034117, 0.002701662365598083],
                },
                "negative_net_folds": 2,
                "negative_adverse_folds": 3,
                "negative_net_fold_concentration": 0.7587523702032738,
                "margin_strata_pass": False,
                "one_hour_delay_pass": False,
            },
        },
        "original_bilateral_pass": False,
        "terminal_verdict": "reject_causal_same_asset_perpetual_vs_spot_range_energy_share_information_premise_1h_v1",
        "pr_closed_unmerged": True,
    }


def return_transmission_group() -> dict[str, Any]:
    return {
        "group": "B",
        "mechanism": "same-underlying lag-one perpetual-to-spot return transmission",
        "issue": 1145,
        "pr": 1146,
        "head": "68820bc787267718a5e772224e2d2949ab54d028",
        "workflow": 31272376253,
        "artifact": 9026025290,
        "artifact_sha256": "9d065907ab420e88ac7fe9be38018c4b384ab43f0999f617f994aa1c77a30202",
        "evidence_sha256": "877c2db7ac62c09dfdc91c38e2a41dce7dea8d741d71c02556664a6006423244",
        "report_sha256": "bffd078e049224a971523e4108c990445c5ca05479d0a13b64ae74f746df8ab3",
        "manifest_sha256": "f13708ff3df3078c1bcd923f9bfe2ef9404d3acf6db0458920a43b862c4c034a",
        "public_provider_native_1h": True,
        "fee_bps_one_way": 5.0,
        "source_arms_passed": "4/4",
        "rows_per_source_arm": 24144,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "sealed_oos_accessed": False,
        "expected_sign": "positive",
        "targets": {
            "BTCUSDT": {
                "opportunities": 285,
                "net_rho": 0.0596873104656648,
                "net_slope": 0.0005823981198103227,
                "net_tercile_effect": 0.0029055485117051565,
                "adverse_rho": 0.008036318833536628,
                "adverse_slope": -0.0003580625982477441,
                "adverse_tercile_effect": 0.0003412228897347533,
                "bootstrap_95": {
                    "net_rho": [-0.04637703887372215, 0.16022309338447172],
                    "net_slope": [-0.002219469768326025, 0.003463652029382579],
                    "adverse_rho": [-0.11132329826365078, 0.11530898275375259],
                    "adverse_slope": [-0.003062140324421543, 0.0019048119263267449],
                },
                "positive_net_folds": 3,
                "positive_adverse_folds": 1,
                "positive_net_fold_concentration": 0.4896871860582785,
                "margin_strata_pass": False,
                "one_hour_delay_pass": True,
            },
            "ETHUSDT": {
                "opportunities": 241,
                "net_rho": -0.018035218270978363,
                "net_slope": -0.000274387282647185,
                "net_tercile_effect": -0.0003661662716824719,
                "adverse_rho": -0.08151126255196979,
                "adverse_slope": -0.0008235696850734943,
                "adverse_tercile_effect": -0.005305589671655507,
                "bootstrap_95": {
                    "net_rho": [-0.13877567266173885, 0.09321840575858904],
                    "net_slope": [-0.0031494078002379, 0.002617298615387936],
                    "adverse_rho": [-0.20640626101725354, 0.03261851696536908],
                    "adverse_slope": [-0.0031848225562875767, 0.0010216407149170451],
                },
                "positive_net_folds": 2,
                "positive_adverse_folds": 0,
                "positive_net_fold_concentration": 0.7337962618646688,
                "margin_strata_pass": False,
                "one_hour_delay_pass": False,
            },
        },
        "original_bilateral_pass": False,
        "terminal_verdict": "reject_causal_same_asset_perpetual_to_spot_return_transmission_information_premise_1h_v1",
        "pr_closed_unmerged": True,
    }


def main() -> None:
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", "UNBOUND")
    a = range_energy_group()
    b = return_transmission_group()
    groups = [a, b]

    assert all(g["pr_closed_unmerged"] for g in groups)
    assert all(g["public_provider_native_1h"] for g in groups)
    assert all(g["fee_bps_one_way"] == FEE_BPS_ONE_WAY for g in groups)
    assert all(g["candidate_count"] == 0 and g["parameter_grid_count"] == 0 for g in groups)
    assert all(not g["sealed_oos_accessed"] for g in groups)
    assert all(not g["original_bilateral_pass"] for g in groups)

    leave_one = [
        {"omitted": "A", "retained": ["B"], "independently_admissible_groups": 0},
        {"omitted": "B", "retained": ["A"], "independently_admissible_groups": 0},
    ]

    retention_gates = {
        "01_exact_terminal_identity_reconciliation": True,
        "02_public_provider_native_1h_and_exact_5bps_contract": True,
        "03_candidate_grid_zero_and_oos_sealed": True,
        "04_at_least_one_original_bilateral_mechanism_admissible": False,
        "05_supporting_group_preserves_preregistered_economic_sign_bilaterally": False,
        "06_supporting_group_passes_dependence_bounds_bilaterally": False,
        "07_supporting_group_passes_breadth_concentration_strata_and_delay_bilaterally": False,
        "08_leave_one_group_out_retains_admissible_mechanism": False,
        "09_no_overlap_context_promoted_to_vote": True,
        "10_no_new_performance_observation": True,
    }
    assert len(retention_gates) == 10
    assert not all(retention_gates.values())

    evidence = {
        "schema_version": 1,
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "base_main": BASE_MAIN,
        "exact_head": exact_head,
        "bar": BAR,
        "fee_bps_one_way_where_economics_defined": FEE_BPS_ONE_WAY,
        "candidate_count": CANDIDATE_COUNT,
        "parameter_grid_count": PARAMETER_GRID_COUNT,
        "new_market_rows": 0,
        "new_target_labels": 0,
        "new_oos_observations": 0,
        "new_fitting_or_tuning": 0,
        "top_level_group_count": 2,
        "independently_admissible_groups": 0,
        "groups": groups,
        "retention_gates": retention_gates,
        "retention_gates_passed": sum(retention_gates.values()),
        "retention_gates_total": len(retention_gates),
        "leave_one_group_out": leave_one,
        "non_voting_overlap_context": [
            "issue_1139_market_participation_share",
            "issue_1108_directional_aggressor_flow_absorption",
            "issues_941_943_814_basis_premium_funding_context",
            "open_interest_positioning_options_onchain_macro_families",
        ],
        "performance": null_performance(),
        "closed_rescue_surface": [
            "alternate range estimators or spot/perpetual range ratios",
            "return-difference or role-reversal reinterpretation",
            "lag-2-plus or Granger-order search",
            "rolling regression beta or alternate baseline/impulse windows",
            "phase scanning, smoothing, z-scores, thresholds or volatility normalization",
            "favourable-fold deletion, sign reversal or single-market promotion",
            "fitted combinations of Groups A and B",
            "OOS rescue",
        ],
        "canonical_mutation": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    evidence_raw = canonical_json(evidence)
    (OUT / "evidence.json").write_bytes(evidence_raw)

    report = f"""# Same-asset spot/perpetual OHLC price-discovery programme closure

- family: `{FAMILY_ID}`
- issue: `#{ISSUE_NUMBER}`
- exact head: `{exact_head}`
- canonical main: `{BASE_MAIN}`
- bar: `1H`
- fee where economics were defined: exactly `5 bps` one way
- candidate/grid: `0/0`
- new rows / labels / OOS / fitting: `0 / 0 / 0 / 0`
- independently admissible mechanisms: `0/2`
- retention gates: `{sum(retention_gates.values())}/10`
- terminal verdict: `{VERDICT}`

Group A (#1143/#1144) passed all four immutable public 1H source arms but failed the original bilateral range-energy information contract. BTC had intended negative return statistics but wrong-signed adverse statistics and no dependence support; ETH was not sign-consistent and failed concentration, strata and +1H transport requirements.

Group B (#1145/#1146) also passed all four immutable public 1H source arms but failed the original bilateral return-transmission contract. BTC had partial positive return information but wrong-signed adverse slope and no dependence support; ETH was wrong-signed on both return and adverse endpoints and failed delay transport.

Removing either group leaves zero independently admissible mechanisms. No overlap-context family is counted as an additional vote. All closure-level executable strategy metrics are null because this closure creates no candidate, selector, position path or equity curve.
"""
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
        "retention_gates": f"{sum(retention_gates.values())}/10",
        "verdict": VERDICT,
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
        "manifest_sha256": manifest_sha,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
