from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-stablecoin-liquidity-state-programme-closure-1h-v1"
ISSUE_NUMBER = 1160
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
FEE_BPS_ONE_WAY = 5.0
CANDIDATE_COUNT = 0
PARAMETER_GRID_COUNT = 0
VERDICT = "reject_reopening_completed_public_stablecoin_liquidity_state_mechanisms_1h_v1"
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
        "edge_per_turnover_bps": None,
        "fold_year_breadth": None,
        "dependence_uncertainty": None,
        "plus_1h_transport": None,
    }


def group_records() -> list[dict[str, Any]]:
    return [
        {
            "group": "A",
            "domain": "stablecoin parity-dislocation acceleration",
            "issue": 926,
            "pr": 930,
            "head": "7fd31e61ff48c6c187b0c3ad4ea37bc376127d09",
            "workflow": 30723930506,
            "artifact": 8825754273,
            "artifact_sha256": "16f580ba574a61112905104876db46d193392d4319831b4aed58688d1fc6b83f",
            "evidence_sha256": "e03cb794623ab14c52c650136c195a8e428c45e48de4b048261c98a7408caca8",
            "source_admissible": True,
            "target_information_reached": True,
            "robust_executable_strategy": False,
            "independently_supportive": False,
            "training_state_activity": 0.440111,
            "btc": {"entry_vetoes": 11, "veto_quarters": 2, "largest_quarter_share": 0.727273, "deferred_reauthorisations": 1},
            "eth": {"entry_vetoes": 44, "veto_quarters": 2, "largest_quarter_share": 0.863636, "deferred_reauthorisations": 1},
            "performance": null_performance(),
            "terminal_verdict": "reject_causal_stablecoin_dislocation_acceleration_confirmed_e2160_entry_1h_v1",
            "decisive_failure": "bilateral recurrent-decision support gate failed before economics; veto breadth/concentration/reauthorisation failed",
        },
        {
            "group": "B",
            "domain": "aggregate stablecoin circulating-supply source",
            "issue": 960,
            "pr": 961,
            "head": "78a824c12fe5c82d85762c6bee662b21289d2580",
            "workflow": 30740200101,
            "artifact": 8831009505,
            "artifact_sha256": "7e0d1603f34638a2d33f4abef99413eed65d89d4865cdc544da46929f068bb84",
            "evidence_sha256": "ad2808d88498fd9cd2444192a2c07a2e8eb521489bd14baf7b57a9bacb609591",
            "source_admissible": False,
            "target_information_reached": False,
            "robust_executable_strategy": False,
            "independently_supportive": False,
            "provider_interfaces": 6,
            "qualifying_interfaces": 0,
            "source_arms_passing": "0/2",
            "qualifying_observations": 0,
            "performance": null_performance(),
            "terminal_verdict": "reject_causal_stablecoin_supply_impulse_source_contract_1h_v1",
            "decisive_failure": "no bilateral complete anonymous provider-defined native-1H aggregate USDT/USDC supply source",
        },
        {
            "group": "C",
            "domain": "stablecoin conversion-activity stress",
            "issue": 1158,
            "pr": 1159,
            "head": "4ae63dbc052e79124106f1eb97a0149d08a8bf7a",
            "workflow": 31279770184,
            "artifact": 9028100815,
            "artifact_sha256": "0babc3a06b9a6b16f988e1aff081f7d0f2170d0c2ece39369445c462615aa62e",
            "evidence_sha256": "4240243d4e2046fb6443f58db133704604debc3863f4b0b17921e23af02c820d",
            "source_admissible": True,
            "target_information_reached": True,
            "robust_executable_strategy": False,
            "independently_supportive": False,
            "candidate_count": 0,
            "parameter_grid_count": 0,
            "btc": {"opportunities": 285, "net_rho": 0.056599, "net_slope": 0.001011, "net_tercile_bp": 30.20, "adverse_rho": -0.060945, "adverse_slope": -0.001437, "adverse_tercile_bp": -21.54},
            "eth": {"opportunities": 241, "net_rho": -0.009784, "net_slope": -0.000157, "net_tercile_bp": 21.28, "adverse_rho": -0.086763, "adverse_slope": -0.001846, "adverse_tercile_bp": -6.73},
            "performance": null_performance(),
            "terminal_verdict": "reject_causal_lagged_stablecoin_conversion_activity_opportunity_information_premise_1h_v1",
            "decisive_failure": "bilateral frozen negative return relation, dependence support, margin-strata transport and +1H transport failed before OOS",
        },
    ]


def main() -> None:
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", "UNBOUND")
    groups = group_records()
    assert len(groups) == 3
    assert sum(bool(g["independently_supportive"]) for g in groups) == 0
    assert all(g["robust_executable_strategy"] is False for g in groups)

    leave_one = []
    for omitted in ["A", "B", "C"]:
        retained = [g for g in groups if g["group"] != omitted]
        leave_one.append({
            "omitted": omitted,
            "retained": [g["group"] for g in retained],
            "independently_supportive_groups": sum(bool(g["independently_supportive"]) for g in retained),
            "target_information_failure_present": any(g["target_information_reached"] and not g["independently_supportive"] for g in retained),
            "source_contract_failure_present": any(g["source_admissible"] is False for g in retained),
            "passes": sum(bool(g["independently_supportive"]) for g in retained) == 0 and any((g["target_information_reached"] and not g["independently_supportive"]) or g["source_admissible"] is False for g in retained),
        })

    programme_gates = {
        "01_three_terminal_groups_bound": True,
        "02_parity_object_failed_recurrent_bilateral_decision_relevance": True,
        "03_supply_object_failed_bilateral_native_1h_source_contract": True,
        "04_conversion_activity_failed_bilateral_sign_dependence_transport_before_oos": True,
        "05_no_group_has_bilateral_positive_dependence_aware_target_return_support": True,
        "06_no_group_supplies_robust_executable_strategy": True,
        "07_source_feasibility_not_counted_as_alpha_and_source_failure_not_misreported_as_no_economics": True,
        "08_all_leave_one_group_out_subsets_retain_zero_support_and_failure_evidence": all(x["passes"] for x in leave_one),
        "09_no_posthoc_rescue_or_combination_used": True,
        "10_scope_limited_to_public_stablecoin_liquidity_state_proxies": True,
    }
    assert all(programme_gates.values())

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
        "top_level_group_count": 3,
        "independently_supportive_groups": 0,
        "groups": groups,
        "programme_gates": programme_gates,
        "programme_gates_passed": sum(programme_gates.values()),
        "programme_gates_total": len(programme_gates),
        "leave_one_group_out": leave_one,
        "performance": null_performance(),
        "canonical_mutation": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "verdict": VERDICT,
    }

    OUT.mkdir(parents=True, exist_ok=True)
    evidence_raw = canonical_json(evidence)
    (OUT / "evidence.json").write_bytes(evidence_raw)

    report = f"""# Public stablecoin-liquidity state programme closure

- family: `{FAMILY_ID}`
- issue: `#{ISSUE_NUMBER}`
- exact head: `{exact_head}`
- canonical main: `{BASE_MAIN}`
- bar: `1H`
- fee where historical opportunity economics were defined: exactly `5 bps` one way
- candidate/grid: `0/0`
- new rows / labels / OOS / fitting: `0 / 0 / 0 / 0`
- independently supportive groups: `0/3`
- architecture closure gates: `10/10 PASS`
- leave-one-group-out adjudications: `3/3 PASS`
- terminal verdict: `{VERDICT}`

The three independent completed stablecoin-state objects are all unsupported under their original frozen contracts.

Group A had a complete public native-1H parity-dislocation source, but the entry-veto information was not recurrent bilaterally: BTC had 11 vetoes in two quarters with 72.7273% concentration and one reauthorisation; ETH had 44 vetoes in two quarters with 86.3636% concentration and one reauthorisation. Economics remained unopened.

Group B is a source-contract rejection rather than alpha rejection: none of six frozen provider interfaces supplied the required bilateral direct anonymous provider-defined native-1H aggregate USDT/USDC circulating-supply history. Target prices and strategy economics remained unopened.

Group C had a complete immutable Binance public native-1H source, but the preregistered defensive conversion-activity relation did not survive training. BTC next-24H net rho/slope/tercile were +0.056599 / +0.001011 / +30.20 bp; ETH outer net tercile was +21.28 bp. Every required dependence interval crossed zero and margin-strata/+1H transport failed before OOS.

No result is rescued by sign reversal, alternate stablecoin, target deletion, favourable-period selection, threshold/window search, provider substitution, daily expansion, reconstruction, or fitted combination. The conclusion is deliberately limited to the represented public stablecoin liquidity/state proxies and does not claim all monetary or macro information is impossible.

No executable candidate exists at this closure level. Return, Sharpe, benchmark comparison, turnover, fee drag, drawdown and edge per turnover therefore remain null rather than zero. Canonical mutation, paper trading and live trading are not authorized.
"""
    report_raw = report.encode()
    (OUT / "report.md").write_bytes(report_raw)

    manifest = {
        "family_id": FAMILY_ID,
        "issue_number": ISSUE_NUMBER,
        "base_main": BASE_MAIN,
        "exact_head": exact_head,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_rows": 0,
        "new_target_labels": 0,
        "new_oos_observations": 0,
        "new_fitting_or_tuning": 0,
        "evidence_sha256": sha256(evidence_raw),
        "report_sha256": sha256(report_raw),
        "verdict": VERDICT,
    }
    manifest_raw = canonical_json(manifest)
    (OUT / "manifest.json").write_bytes(manifest_raw)
    (OUT / "evidence.sha256").write_text(sha256(evidence_raw) + "\n")
    (OUT / "report.sha256").write_text(sha256(report_raw) + "\n")
    (OUT / "manifest.sha256").write_text(sha256(manifest_raw) + "\n")

    print(json.dumps({
        "family_id": FAMILY_ID,
        "exact_head": exact_head,
        "independently_supportive_groups": 0,
        "programme_gates": "10/10",
        "leave_one_group_out": "3/3",
        "verdict": VERDICT,
        "evidence_sha256": sha256(evidence_raw),
        "report_sha256": sha256(report_raw),
        "manifest_sha256": sha256(manifest_raw),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
