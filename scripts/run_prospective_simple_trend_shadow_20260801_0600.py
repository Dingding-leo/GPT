from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260801_0500 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_553_200_000
REALIZED_DECISION_HOUR_MS = 1_785_556_800_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_560_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_564_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_542_400_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "332add83f4f5461a3a6f0ae703417b3f5677146d8513a8a1adf00efb57448caf"
PRIOR_ARTIFACT_SHA256 = "06a5f6b37ea1049b4da72ca5fc3424d4f95905f1aa40dfab2fc72e2160fa67c8"


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
        "# Prospective simple-trend shadow through 06:00 UTC on 1 August 2026",
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
        lines.append(
            f"| {market['instrument']} | {recent['long_decision_count']}/{recent['realized_interval_count']} | "
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
        "The preregistered `causal-trend-episode-maturity-filter-1h-v1` candidate is terminally rejected. BTC-USDT returned -8.223363% net OOS with Sharpe -0.097706 versus E2160 at -6.556128% and -0.073035; ETH-USDT returned -17.789927% with Sharpe -0.106779 versus E2160 at -12.384330% and -0.010359. Both markets passed only 2/11 gates. Reduced turnover did not offset adverse gross timing, dependence-aware superiority failed, and no same-cohort maturity/dwell rescue is authorised.",
        "",
        "The separately preregistered OKX L2 bid-replenishment source-feasibility diagnostic remains pending and has candidate count zero. It cannot alter this policy or epoch unless its information premise is accepted and a later executable rule is independently frozen before OOS access.",
        "",
        "## Machine-readable verdict",
        "",
        "```json",
        json.dumps({
            "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
            "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
            "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
            "candidate_verdict": result["active_alpha_context"]["verdict"],
            "candidate_markets_passing": result["active_alpha_context"]["markets_passing_all_gates"],
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
    result["window"]["prior_cumulative_realized_hours"] = 580
    result["window"]["updated_cumulative_realized_hours"] = 581
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 855,
        "pull_request": 856,
        "family_id": "causal-trend-episode-maturity-filter-1h-v1",
        "status": "terminal_rejection",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "markets_passing_all_gates": 0,
        "correction_permitted": False,
        "exact_head": "2b77f75fb39e67654245b6861c43b0c5127a88a2",
        "workflow_run": 30687606392,
        "artifact_id": 8814500892,
        "artifact_sha256": "05e161b9ca4a03e08b017adda8501509082b8c1eb520ec0bd76b929efa53d2ff",
        "evidence_sha256": "d96c503865c27e71d2a049ac18f4962dfec93bb114db3ebcd6e1576ce752a7c0",
        "gates_passed_per_market": 2,
        "gates_total_per_market": 11,
        "btc_candidate_oos_net": -0.08223362611192064,
        "btc_candidate_oos_sharpe": -0.09770567362930259,
        "btc_e2160_oos_net": -0.06556128319321897,
        "btc_e2160_oos_sharpe": -0.07303549866632462,
        "eth_candidate_oos_net": -0.17789927,
        "eth_candidate_oos_sharpe": -0.106779,
        "eth_e2160_oos_net": -0.12384330,
        "eth_e2160_oos_sharpe": -0.010359,
        "verdict": "reject_causal_trend_episode_maturity_filter_1h_v1",
        "pending_information_issue": 854,
        "pending_information_pull_request": 858,
        "pending_information_family": "okx-l2-bid-replenishment-resilience-opportunity-diagnostic-1h-v1",
        "pending_information_candidate_count": 0,
        "pending_information_status": "source_feasibility_in_progress",
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the trend-episode maturity candidate failed bilateral OOS, breadth, uncertainty, drawdown, delay and edge-per-turnover gates; the pending L2 source diagnostic has no executable candidate",
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": "the new interval contains frozen long exposure" if exposed else "the new interval is cash-only and cannot validate conditional-long persistence",
    }
    result["next_strategy_action"] = "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation; keep the rejected trend-episode maturity family closed, and treat the pending L2 bid-replenishment work only as an information-premise gate with no policy or epoch authority"
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
