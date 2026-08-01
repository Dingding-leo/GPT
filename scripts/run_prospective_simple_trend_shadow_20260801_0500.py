from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260801_0400 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_549_600_000
REALIZED_DECISION_HOUR_MS = 1_785_553_200_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_556_800_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_560_400_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_538_800_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "5e42ae43f235994d1408a760c133e801e14ae029ac96abd25eac2c1755f29744"
PRIOR_ARTIFACT_SHA256 = "30ed498d054efa51abe861cd8bc3777f094882c907c1b53d40a70b545adc9466"


def configure() -> None:
    for name in (
        "PREVIOUS_DECISION_HOUR_MS",
        "REALIZED_DECISION_HOUR_MS",
        "PRIOR_REPORTED_SIGNAL_HOUR_MS",
        "LATEST_COMPLETE_SIGNAL_HOUR_MS",
        "RECENT_WINDOW_FIRST_DECISION_HOUR_MS",
        "RECENT_WINDOW_LAST_DECISION_HOUR_MS",
        "PRIOR_RESULT_SHA256",
        "PRIOR_ARTIFACT_SHA256",
    ):
        setattr(prior, name, globals()[name])


def pct(value: float | None) -> str:
    return "undefined" if value is None else f"{100.0 * value:+.6f}%"


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow through 05:00 UTC on 1 August 2026",
        "",
        f"- Policy: `{result['policy_name']}`",
        f"- Acquisition: `{result['acquisition']['server_time']}`",
        f"- Latest complete signal bar: `{result['window']['latest_complete_signal_bar_start']}`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Abort: `{result['abort_conditions']['triggered']}`",
        "",
        "| Market | Position | New target | Net | Benchmark | Residual | Turnover | Fees | Margin | Drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realised = market["realized_interval"]
        lines.append(
            f"| {market['instrument']} | {'Long' if realised['position'] else 'Cash'} | "
            f"{'Long' if market['new_decisions'][0]['target'] else 'Cash'} | "
            f"{pct(realised['net_strategy_return'])} | {pct(realised['asset_return'])} | "
            f"{pct(realised['strategy_residual_vs_buy_and_hold'])} | {realised['turnover']} | "
            f"{pct(realised['modeled_fee'])} | {pct(market['new_decisions'][0]['margin'])} | "
            f"{pct(market['discrepancy_diagnosis']['signal_margin_change'])} |"
        )
    lines.extend([
        "",
        "## Five-interval scorecard",
        "",
        "| Market | Longs | Net | Benchmark | Residual | Turnover | Fees | Max DD | Sharpe | Edge/turnover |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for market in result["markets"]:
        recent = market["recent_forward_window"]
        sharpe = "undefined" if recent["sharpe"] is None else f"{recent['sharpe']:.6f}"
        edge = "undefined" if recent["edge_per_turnover_bps"] is None else f"{recent['edge_per_turnover_bps']:.6f}"
        longs = sum(int(row["position"]) for row in recent["intervals"])
        lines.append(
            f"| {market['instrument']} | {longs}/{recent['realized_interval_count']} | "
            f"{pct(recent['net_compound_return'])} | {pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | {sharpe} | {edge} |"
        )
    drift = result["strategy_facing_discrepancy"]
    lines.extend([
        "",
        "## Drift diagnosis",
        "",
        f"- Instrument: `{drift['selected_instrument']}`",
        f"- Classification: `{drift['classification']}`",
        f"- Latest benchmark: `{pct(drift['latest_interval_asset_return'])}`",
        f"- Five-interval benchmark: `{pct(drift['five_interval_benchmark_return'])}`",
        f"- Margin drift: `{pct(drift['trend_margin_drift'])}`",
        f"- Policy/accounting defect: `{drift['policy_or_accounting_defect_detected']}`",
        "",
        drift["diagnosis"],
        "",
        "## Candidate disposition",
        "",
        "The frozen `direct-temporal-representation-family-closure-1h-v1` evidence is terminally negative. Across the Haar and historical-analog architectures, the cross-architecture median net effect was -0.409443 bp/hour, the median Sharpe effect was -0.169692, zero of eight primary uncertainty lower bounds were positive, zero of four candidates survived the 24H delay stress, and only 1/13 family gates passed. No same-family correction is authorised.",
        "",
        "Issue #855 / PR #856 preregister a distinct zero-grid causal trend-episode maturity filter over E2160 on BTC and ETH. It remains an unadjudicated candidate and cannot modify this prospective epoch unless every bilateral frozen gate passes on exact-head evidence.",
        "",
        "## Machine-readable verdict",
        "",
        "```json",
        json.dumps({
            "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
            "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
            "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
            "correction_permitted": result["training_authorized_correction"]["permitted"],
            "correction_applied": result["training_authorized_correction"]["applied"],
            "observation_epoch_restarted": result["training_authorized_correction"]["observation_epoch_restarted"],
            "abort_triggered": result["abort_conditions"]["triggered"],
            "verdict": result["verdict"],
            "paper_trading_authorized": result["paper_trading_authorized"],
            "live_trading_authorized": result["live_trading_authorized"],
        }, sort_keys=True, indent=2),
        "```",
        "",
        f"Next strategy-facing action: {result['next_strategy_action']}.",
        "",
    ])
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 579
    result["window"]["updated_cumulative_realized_hours"] = 580
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 851,
        "pull_request": 853,
        "family_id": "direct-temporal-representation-family-closure-1h-v1",
        "status": "terminal_rejection",
        "candidate_count": 0,
        "source_architectures": 2,
        "source_market_candidates": 4,
        "parameter_grid_count": 0,
        "correction_permitted": False,
        "exact_head": "ca78a26893f53f33b6070a396a5f17ca3399e5b7",
        "workflow_run": 30686614028,
        "artifact_id": 8814138902,
        "artifact_sha256": "377b66227cc5b8c7955ce0b21868a559dca7fc03ea6288357b2500749aadc63f",
        "evidence_sha256": "e2ffae9c60ac2512be2d72dc342270cebe359ee65f220e1d56fafacab975f69f",
        "gates_passed": 1,
        "gates_total": 13,
        "cross_architecture_median_net_effect_bps_per_hour": -0.409443,
        "cross_architecture_median_sharpe_effect": -0.169692,
        "positive_primary_lower_bounds": 0,
        "primary_lower_bounds_total": 8,
        "delay_survivors": 0,
        "delay_candidates_total": 4,
        "verdict": "reject_direct_temporal_representation_architecture_family",
        "next_preregistered_issue": 855,
        "next_preregistered_pull_request": 856,
        "next_preregistered_family": "causal-trend-episode-maturity-filter-1h-v1",
        "next_candidate_status": "pending_exact_head_terminal_evidence",
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the direct temporal-representation family is terminally rejected and the separately frozen trend-episode maturity candidate has not passed every bilateral gate",
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": "the new interval contains frozen long exposure" if exposed else "the new interval is cash-only and cannot validate conditional-long persistence",
    }
    result["next_strategy_action"] = "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation; keep the direct temporal-representation family closed, and permit no correction or epoch restart unless the independently frozen trend-episode maturity filter passes every bilateral gate on immutable exact-head evidence"
    base.write_outputs(output_dir, result)
    write_report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"))
    args = parser.parse_args()
    print(json.dumps(run(args.output_dir, args.base_url.rstrip("/")), sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
