from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

FAMILY_ID = "causal-public-same-underlying-leveraged-market-information-programme-closure-1h-v1"
ISSUE_NUMBER = 1151
BASE_MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"
BAR = "1H"
FEE_BPS_ONE_WAY = 5.0
CANDIDATE_COUNT = 0
PARAMETER_GRID_COUNT = 0
VERDICT = "reject_reopening_completed_public_same_underlying_leveraged_market_information_mechanisms_1h_v1"
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
            "domain": "directional aggressor flow and absorption",
            "issue": 1108,
            "pr": 1109,
            "head": "a0b8b3db01d12671eb4a35b0e3cba40677a2b0dd",
            "workflow": 31251090067,
            "artifact": 9020019032,
            "artifact_sha256": "aec539ef825848b42d421d7336b637a3a7f80441a205a83cb4806d05a41db89a",
            "evidence_sha256": "c2b290e55f31874c675b058d0f4121be51d78c867e524376a0418c66240ccc9e",
            "report_sha256": "935fbfae34a1f1f54c41a20f4c1c7b9b16c39891b341df2b51a060a636d383b7",
            "manifest_sha256": "2ef14e02969eef13ceee86c3b7a2f8e7abf000cd387835a91357ca1d0056a190",
            "internal_groups": 3,
            "independently_admissible_internal_groups": 0,
            "independently_supportive": False,
            "source_admissible": None,
            "target_return_evidence_reached": True,
            "pr_closed_unmerged": True,
            "terminal_verdict": "reject_reopening_completed_directional_aggressor_flow_absorption_mechanisms_1h_v1",
            "decisive_failure": "zero independently admissible mechanisms; favourable point estimates fail training, breadth, drawdown and dependence transport",
            "shared_historical_context_ref": "issue_642",
        },
        {
            "group": "B",
            "domain": "direct public positioning and inventory",
            "issue": 1127,
            "pr": 1128,
            "head": "18a3fc1142eadcb7842f8ee6970a65292508d568",
            "workflow": None,
            "artifact": None,
            "artifact_sha256": None,
            "evidence_sha256": None,
            "report_sha256": None,
            "manifest_sha256": None,
            "internal_groups": 4,
            "independently_admissible_internal_groups": 0,
            "independently_supportive": False,
            "source_admissible": False,
            "target_return_evidence_reached": False,
            "pr_closed_unmerged": True,
            "terminal_verdict": "reject_reopening_completed_public_direct_positioning_inventory_source_mechanisms_1h_v1",
            "decisive_failure": "zero of four source groups proves a complete bilateral nonconstant provider-native 1H panel",
        },
        {
            "group": "C",
            "domain": "trading participation and activity composition",
            "issue": 1141,
            "pr": 1142,
            "head": "7c50351f83df300f272fc13a83bf74d2ca9b2a45",
            "workflow": 31270037104,
            "artifact": 9025317116,
            "artifact_sha256": "742382659b6dc62eed47a33bc9a830fb962c6f365061b8376db2cc958c404052",
            "evidence_sha256": "3d84b3e5b67d4565a0f7ec81e8dfab4ac76073681f70cfdd1348ec254638ce8d",
            "report_sha256": "00ea603870bb2b7e4eac55e2295db000b008a7a01d6491fae5e3b6239b690276",
            "manifest_sha256": "fa0d84f0a083fa3b939cbde96b20a2c2e5a0db3c2a565c8dc42129f715c7ff6a",
            "internal_groups": 2,
            "independently_admissible_internal_groups": 0,
            "independently_supportive": False,
            "source_admissible": True,
            "target_return_evidence_reached": True,
            "pr_closed_unmerged": True,
            "terminal_verdict": "reject_reopening_completed_public_market_participation_composition_mechanisms_1h_v1",
            "decisive_failure": "zero of two mechanisms survives original bilateral economics/information, dependence, breadth and delay gates",
            "shared_historical_context_ref": "issue_642",
        },
        {
            "group": "D",
            "domain": "same-asset spot/perpetual OHLC price discovery",
            "issue": 1147,
            "pr": 1148,
            "head": "860ff63405451e68766540bdade4c6486ca4c26e",
            "workflow": 31274055646,
            "artifact": 9026475781,
            "artifact_sha256": "beaa52f763f1851e38da329f19c0d7430b2a4a1e92487eb6ff388e6d88bd1620",
            "evidence_sha256": "f299090688f861cae4687d9953c20b8956e2ef7bd2a25d8e0fc203a289725a1a",
            "report_sha256": "56219adc95d0be85dd386faa632f8bf0035d06dc460695dd756ceefd851e7850",
            "manifest_sha256": "526c2cf61d221dcea79d31eb01508cb61aba5276f6614f2f8b42fba3a5022e0d",
            "internal_groups": 2,
            "independently_admissible_internal_groups": 0,
            "independently_supportive": False,
            "source_admissible": True,
            "target_return_evidence_reached": True,
            "pr_closed_unmerged": True,
            "terminal_verdict": "reject_reopening_completed_same_asset_spot_perpetual_ohlc_price_discovery_mechanisms_1h_v1",
            "decisive_failure": "zero of two OHLC-only mechanisms passes original bilateral sign, dependence, breadth, concentration, strata and +1H transport",
        },
        {
            "group": "E",
            "domain": "direct forced-liquidation intensity source",
            "issue": 1149,
            "pr": 1150,
            "head": "da6e349eec2fb5b3ecb3517d95340d598490e4ab",
            "workflow": 31274767456,
            "artifact": 9026678161,
            "artifact_sha256": "5780d436cd57dcdead696721ebf5d953279796aa18893b2015513e9a77e19b0e",
            "evidence_sha256": "9ed400e979dc8fdedb557549b66b3203f6f9e93fee0d9e8a27f8eeb72da81ff2",
            "report_sha256": "edcb4634ad254361011a31f2bba18df77669e62969f90532edd7842e06e5cfe6",
            "manifest_sha256": "01112d330eb0b849d47bb28866587816ff6d049b0cebfdef3f1733a9e1718d3e",
            "providers_audited": 3,
            "providers_passing": 0,
            "source_gates_passed": 3,
            "source_gates_total": 14,
            "independently_supportive": False,
            "source_admissible": False,
            "target_return_evidence_reached": False,
            "pr_closed_unmerged": True,
            "terminal_verdict": "reject_causal_public_forced_liquidation_intensity_source_contract_1h_v1",
            "decisive_failure": "zero of three frozen official providers exposes replayable direct historical provider-defined 1H liquidation aggregates bilaterally",
        },
    ]


def main() -> None:
    exact_head = os.environ.get("RESEARCH_HEAD_SHA", "UNBOUND")
    groups = group_records()
    assert len(groups) == 5
    assert all(g["pr_closed_unmerged"] for g in groups)
    assert sum(bool(g["independently_supportive"]) for g in groups) == 0

    # One reconciliation repair: issue #642 appears inside both terminal Group A and
    # Group C histories. It is one historical mechanism, not two independent votes.
    overlap_reconciliation = {
        "issue": 642,
        "appears_in_groups": ["A", "C"],
        "independent_vote_count": 0,
        "reason": "shared rejected historical mechanism; retained only as non-voting comparator context",
        "strategy_values_changed": False,
        "group_dispositions_changed": False,
        "gate_values_changed": False,
    }

    shared_historical_context = {
        "issue_642": {
            "mechanism": "volume-weighted directional persistence",
            "fee_bps_one_way": 5.0,
            "BTC": {
                "train_return": -0.2465,
                "train_sharpe": -0.428,
                "oos_return": 1.4118,
                "oos_sharpe": 1.071,
                "oos_turnover": 23,
                "benchmark_oos_turnover": 45,
                "oos_edge_per_turnover_bps": 451.96,
                "benchmark_edge_per_turnover_bps": 212.75,
                "maximum_drawdown": -0.3094,
                "benchmark_maximum_drawdown": -0.2655,
                "profitable_folds": 6,
                "folds": 12,
                "paired_mean_delta_lower_bound": -0.0787,
                "paired_sharpe_delta_lower_bound": -0.1997,
            },
            "ETH": {
                "train_return": -0.2411,
                "train_sharpe": -0.287,
                "oos_return": 1.4070,
                "oos_sharpe": 0.899,
                "oos_turnover": 10,
                "benchmark_oos_turnover": 30,
                "oos_edge_per_turnover_bps": 1159.89,
                "benchmark_edge_per_turnover_bps": 283.58,
                "profitable_folds": 6,
                "folds": 12,
                "paired_mean_delta_lower_bound": -0.0193,
                "paired_sharpe_delta_lower_bound": -0.0280,
            },
            "independent_support_vote": False,
        }
    }

    leave_one = []
    labels = [g["group"] for g in groups]
    for omitted in labels:
        retained = [x for x in labels if x != omitted]
        leave_one.append({
            "omitted": omitted,
            "retained": retained,
            "independently_supportive_groups": 0,
        })

    programme_gates = {
        "01_exact_five_group_identity_and_disposition_reconciliation": True,
        "02_at_least_two_of_five_groups_independently_supportive": False,
        "03_supportive_executable_group_positive_required_train_oos_full_economics_bilaterally": False,
        "04_supportive_group_bilateral_dependence_aware_support": False,
        "05_supportive_group_breadth_concentration_and_latency_transport_bilaterally": False,
        "06_source_admissibility_or_complete_native_1h_target_return_evidence_exists": True,
        "07_no_support_requires_prohibited_rescue": True,
        "08_every_leave_one_group_out_subset_retains_support": False,
        "09_source_failures_remain_source_failures_and_null_strategy_metrics_remain_null": True,
        "10_conclusion_limited_to_five_completed_public_leveraged_market_routes": True,
    }
    assert sum(programme_gates.values()) == 5
    assert not all(programme_gates.values())

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
        "top_level_group_count": 5,
        "independently_supportive_groups": 0,
        "groups": groups,
        "shared_historical_context": shared_historical_context,
        "overlap_reconciliation": overlap_reconciliation,
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

    report = f"""# Public same-underlying leveraged-market information programme closure

- family: `{FAMILY_ID}`
- issue: `#{ISSUE_NUMBER}`
- exact head: `{exact_head}`
- canonical main: `{BASE_MAIN}`
- bar: `1H`
- fee where historical economics were defined: exactly `5 bps` one way
- new candidate/grid: `0/0`
- new rows / labels / OOS / fitting: `0 / 0 / 0 / 0`
- independently supportive top-level groups: `0/5`
- programme gates: `{sum(programme_gates.values())}/10`
- leave-one-group-out support: `0` in every one of five subsets
- terminal verdict: `{VERDICT}`

The five frozen routes are all terminally unsupported under their original contracts: directional aggressor-flow/absorption, direct positioning/inventory, participation/activity composition, OHLC-only spot/perpetual price discovery, and direct forced-liquidation sourcing.

One evidence-reconciliation defect was repaired without changing any strategy value or gate: historical issue #642 appears inside both terminal Group A and Group C histories. It is retained once as non-voting historical comparator context and contributes zero independent support votes. Its attractive OOS point estimates remain contradicted by negative bilateral training economics, 6/12 fold breadth and non-positive dependence lower bounds.

Groups C and D did reach target-return evidence from complete immutable public provider-native 1H sources, so source-to-label feasibility exists for some mechanisms. That does not satisfy alpha-support gates because both terminal programmes rejected every unchanged mechanism. Source Groups B and E failed source admissibility and therefore retain null strategy economics.

No closure-level executable strategy is created. Train/OOS/full return and Sharpe, benchmark comparison, turnover, fee drag, maximum drawdown, edge per turnover, breadth, dependence uncertainty and +1H strategy performance are all null rather than zero.
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
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_rows": 0,
        "new_target_labels": 0,
        "new_oos_observations": 0,
        "new_fitting_or_tuning": 0,
        "verdict": VERDICT,
    }
    manifest_raw = canonical_json(manifest)
    (OUT / "manifest.json").write_bytes(manifest_raw)
    (OUT / "manifest.sha256").write_text(sha256(manifest_raw) + "\n")

    print(json.dumps({
        "evidence_sha256": evidence_sha,
        "report_sha256": report_sha,
        "manifest_sha256": sha256(manifest_raw),
        "programme_gates_passed": sum(programme_gates.values()),
        "independently_supportive_groups": 0,
        "verdict": VERDICT,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
