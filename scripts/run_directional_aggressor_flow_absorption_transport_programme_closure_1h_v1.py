from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

FAMILY = "causal-directional-aggressor-flow-absorption-transport-programme-closure-1h-v1"
VERDICT = "reject_reopening_completed_directional_aggressor_flow_absorption_mechanisms_1h_v1"
MAIN = "5a0fcc97d1a882f8223656c51f5bb8055f534e38"


def _fail(message: str) -> None:
    raise ValueError(message)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        _fail("source records must be a JSON object")
    return payload


def _validate(source: dict[str, Any]) -> list[dict[str, Any]]:
    if source.get("family_id") != FAMILY:
        _fail("family identity mismatch")
    if source.get("frozen_at_main") != MAIN:
        _fail("frozen main mismatch")
    if source.get("fee_bps_one_way_where_executable") != 5.0:
        _fail("fee mismatch")
    for key, expected in {
        "new_candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data_rows": 0,
        "new_target_labels": 0,
        "new_fitting_or_tuning": 0,
    }.items():
        if source.get(key) != expected:
            _fail(f"{key} mismatch")
    if source.get("new_oos_access") is not False:
        _fail("new OOS access is prohibited")

    groups = source.get("groups")
    if not isinstance(groups, list) or len(groups) != 3:
        _fail("expected exactly three top-level groups")
    expected_ids = [
        "spot_microstructure_resilience_closure",
        "own_price_directional_volume_interaction_closure",
        "same_underlying_perpetual_taker_flow_absorption",
    ]
    if [group.get("group_id") for group in groups] != expected_ids:
        _fail("top-level group ordering/identity mismatch")
    if any(group.get("independently_admissible") is not False for group in groups):
        _fail("terminal records unexpectedly contain support")

    a, b, c = groups
    if a.get("terminal_verdict") != "reject_causal_microstructure_resilience_family":
        _fail("#861 terminal verdict mismatch")
    if a.get("supportive_internal_groups") != 0 or a.get("internal_group_count") != 4:
        _fail("#861 support accounting mismatch")
    if a.get("dimension_pass_counts") != {
        "dependence_aware_support": 0,
        "positive_economics_or_information": 0,
        "replication_or_latency": 0,
        "source_executable": 3,
        "temporal_breadth": 1,
    }:
        _fail("#861 dimension accounting mismatch")

    if b.get("terminal_verdict") != (
        "reject_reopening_completed_own_price_volume_directional_interaction_mechanisms_1h_v1"
    ):
        _fail("#1027 terminal verdict mismatch")
    if b.get("supportive_internal_groups") != 0 or b.get("historical_candidate_count") != 8:
        _fail("#1027 support/candidate accounting mismatch")
    if b.get("closure_gates_passed") != 3 or b.get("closure_gates_total") != 12:
        _fail("#1027 gate accounting mismatch")

    if c.get("terminal_verdict") != (
        "reject_causal_same_asset_perpetual_taker_flow_absorption_information_premise_1h_v1"
    ):
        _fail("#1105 terminal verdict mismatch")
    if c.get("historical_candidate_count") != 0 or c.get("sealed_oos_accessed") is not False:
        _fail("#1105 candidate/OOS accounting mismatch")
    if set(c.get("fixed_targets", [])) != {"SOL-USDT", "XRP-USDT"}:
        _fail("#1105 fixed target mismatch")
    for target in ("SOL-USDT", "XRP-USDT"):
        row = c["targets"][target]
        if row["margin_strata_pass"] or row["delay_transport_pass"]:
            _fail(f"#1105 {target} transport unexpectedly supportive")
    return groups


def _build(source: dict[str, Any], source_sha: str, tested_head: str) -> dict[str, Any]:
    groups = _validate(source)
    b = groups[1]
    c = groups[2]
    persistence = b["strongest_executable_highlight"]

    gate_vector = {
        "identities_and_terminal_dispositions_reconcile": True,
        "independently_admissible_bilateral_mechanism_exists": False,
        "positive_required_train_oos_full_economics_exists": False,
        "bilateral_point_estimate_benchmark_return_and_sharpe_superiority_exists": True,
        "joint_drawdown_turnover_edge_efficiency_pass_exists": False,
        "temporal_breadth_and_concentration_pass_exists": False,
        "strictly_positive_bilateral_dependence_lower_bounds_exist": False,
        "all_applicable_latency_transport_supportive": False,
        "every_leave_one_top_level_group_out_subset_retains_support": False,
        "no_post_hoc_rescue_required_for_conclusion": True,
    }
    leave_one = [
        {"removed_group": group["group_id"], "retained_supportive_groups": 0}
        for group in groups
    ]
    strategy_metrics = {
        "training_return": None,
        "training_sharpe": None,
        "oos_return": None,
        "oos_sharpe": None,
        "full_return": None,
        "full_sharpe": None,
        "benchmark_comparison": None,
        "turnover": None,
        "fee_drag": None,
        "max_drawdown": None,
        "edge_per_turnover": None,
        "calendar_year_breadth": None,
        "strategy_uncertainty": None,
    }
    return {
        "family_id": FAMILY,
        "classification": "zero-candidate immutable-evidence strategy-family closure",
        "tested_head": tested_head,
        "frozen_at_main": MAIN,
        "source_records_sha256": source_sha,
        "top_level_group_count": 3,
        "supportive_top_level_group_count": 0,
        "new_candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data_rows": 0,
        "new_target_labels": 0,
        "new_oos_access": False,
        "new_fitting_or_tuning": 0,
        "fee_bps_one_way_where_executable": 5.0,
        "historical_candidate_count_known_minimum": 8,
        "historical_candidate_count_complete": False,
        "historical_candidate_count_note": (
            "#1027 exposes 8 historical candidates; #861 does not expose an additive family total, "
            "so the programme preserves that top-level count as null rather than inferring it."
        ),
        "group_audit": [
            {
                "group_id": group["group_id"],
                "family_id": group["family_id"],
                "issue": group["issue"],
                "terminal_verdict": group["terminal_verdict"],
                "independently_admissible": False,
                "historical_candidate_count": group.get("historical_candidate_count"),
                "evidence_head": group["evidence_head"],
                "evidence_sha256": group["evidence_sha256"],
            }
            for group in groups
        ],
        "gate_vector": gate_vector,
        "closure_gate_pass_count": sum(gate_vector.values()),
        "closure_gate_total": len(gate_vector),
        "leave_one_top_level_group_out": leave_one,
        "strongest_point_estimate": {
            "mechanism": persistence["mechanism"],
            "training_net_return": persistence["training_net_return"],
            "development_oos": persistence["oos"],
            "interpretation": (
                "OOS return/Sharpe and edge-per-turnover improve bilaterally, but training is negative "
                "in both markets, BTC drawdown worsens, breadth is 6/12 in both markets, and paired "
                "dependence lower bounds are negative."
            ),
        },
        "latest_flow_information": {
            "family_id": c["family_id"],
            "targets": c["targets"],
            "interpretation": (
                "SOL has mixed return point estimates but adverse information is negative; XRP is "
                "negative on return and adverse endpoints. Both fail dependence, breadth, margin-strata "
                "and latency transport."
            ),
        },
        "strategy_metrics": strategy_metrics,
        "sealed_oos_accessed": False,
        "canonical_mutation": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
        "accepted": False,
        "verdict": VERDICT,
        "closed_rescue_surface": [
            "raw taker-buy share or pressure",
            "signed-flow persistence",
            "linear flow/price residuals",
            "candle-efficiency-minus-flow absorption",
            "taker-buy base-volume substitution",
            "effort/result residuals",
            "onset flow vetoes or flow-driven fractional sizing",
            "flow z-scores and alternate 24H/168H/720H windows",
            "smoothing, clipping, winsorisation or sign reversal",
            "post-hoc basis/funding interactions",
            "target substitution, favourable-period deletion or rejected-flow combinations",
        ],
    }


def _report(evidence: dict[str, Any]) -> str:
    latest = evidence["latest_flow_information"]["targets"]
    sol = latest["SOL-USDT"]
    xrp = latest["XRP-USDT"]
    strong = evidence["strongest_point_estimate"]["development_oos"]
    lines = [
        "# Directional aggressor-flow / absorption transport programme closure",
        "",
        f"Verdict: `{evidence['verdict']}`.",
        "",
        "No new market row, target label, OOS observation, candidate, parameter, bootstrap draw or fitted value was used.",
        f"Top-level support: `{evidence['supportive_top_level_group_count']}/{evidence['top_level_group_count']}`; closure gates: `{evidence['closure_gate_pass_count']}/{evidence['closure_gate_total']}`.",
        "",
        "## Strongest historical point estimate",
        "",
        f"BTC #642 OOS: candidate `{strong['BTC-USDT']['candidate_net_return']:.2%}` / Sharpe `{strong['BTC-USDT']['candidate_sharpe']:.3f}` versus B1 `{strong['BTC-USDT']['benchmark_net_return']:.2%}` / `{strong['BTC-USDT']['benchmark_sharpe']:.3f}`; turnover `{strong['BTC-USDT']['candidate_turnover']}` versus `{strong['BTC-USDT']['benchmark_turnover']}`, drawdown `{strong['BTC-USDT']['candidate_max_drawdown']:.2%}` versus `{strong['BTC-USDT']['benchmark_max_drawdown']:.2%}`.",
        f"ETH #642 OOS: candidate `{strong['ETH-USDT']['candidate_net_return']:.2%}` / Sharpe `{strong['ETH-USDT']['candidate_sharpe']:.3f}` versus B1 `{strong['ETH-USDT']['benchmark_net_return']:.2%}` / `{strong['ETH-USDT']['benchmark_sharpe']:.3f}`; turnover `{strong['ETH-USDT']['candidate_turnover']}` versus `{strong['ETH-USDT']['benchmark_turnover']}`.",
        "Both #642 training returns were negative; both markets had only 6/12 profitable folds and negative dependence lower bounds.",
        "",
        "## Fresh same-underlying perpetual-flow evidence",
        "",
        f"SOL: `{sol['opportunities']}` opportunities, net rho/slope `{sol['net_rho']:.6f}` / `{sol['net_slope']:.6f}`, net tercile `{sol['net_tercile_effect']*10000:+.2f} bp`; adverse rho/slope `{sol['adverse_rho']:.6f}` / `{sol['adverse_slope']:.6f}`, adverse tercile `{sol['adverse_tercile_effect']*10000:+.2f} bp`; folds `{sol['positive_net_folds']}/4` net and `{sol['positive_adverse_folds']}/4` adverse.",
        f"XRP: `{xrp['opportunities']}` opportunities, net rho/slope `{xrp['net_rho']:.6f}` / `{xrp['net_slope']:.6f}`, net tercile `{xrp['net_tercile_effect']*10000:+.2f} bp`; adverse rho/slope `{xrp['adverse_rho']:.6f}` / `{xrp['adverse_slope']:.6f}`, adverse tercile `{xrp['adverse_tercile_effect']*10000:+.2f} bp`; folds `{xrp['positive_net_folds']}/4` net and `{xrp['positive_adverse_folds']}/4` adverse.",
        "Both targets failed dependence, margin-strata and +1H transport; XRP adverse-slope 95% interval is entirely negative.",
        "",
        "## Disposition",
        "",
        "All three top-level completed directional-flow groups are terminally unsupported under their original bilateral gates. Every leave-one-top-level-group-out set retains zero support. Further algebraic directional-flow rescues are closed on consumed evidence.",
        "",
        "Closure-level train/OOS/full strategy return and Sharpe, benchmark, turnover, drawdown, edge per turnover, year breadth and strategy uncertainty are null because this run created no executable strategy path.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--tested-head", required=True)
    args = parser.parse_args()

    source_path = Path(args.source)
    source_bytes = source_path.read_bytes()
    source = _read(source_path)
    evidence = _build(source, _sha(source_bytes), args.tested_head)

    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    evidence_bytes = (json.dumps(evidence, sort_keys=True, indent=2) + "\n").encode()
    report_bytes = _report(evidence).encode()
    (output / "evidence.json").write_bytes(evidence_bytes)
    (output / "report.md").write_bytes(report_bytes)
    (output / "source-records.json").write_bytes(source_bytes)
    manifest = {
        "evidence.json": _sha(evidence_bytes),
        "report.md": _sha(report_bytes),
        "source-records.json": _sha(source_bytes),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(VERDICT)
    print("EVIDENCE_SHA256", manifest["evidence.json"])


if __name__ == "__main__":
    main()
