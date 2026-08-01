from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260801_0300 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_546_000_000
REALIZED_DECISION_HOUR_MS = 1_785_549_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_553_200_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_556_800_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_535_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "aa35e4511d917d78133e8977138c810968fd30704d35f7a4bb98edf174eafcaa"
PRIOR_ARTIFACT_SHA256 = "a0d7376d725720ac842d4da93604f0f1706e56029f9a787a84f5a7ecfe5e801d"


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
        "# Prospective simple-trend shadow through 04:00 UTC on 1 August 2026",
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
        "The latest completed direct temporal candidate, `causal-historical-analog-consensus-abstention-1h-v1`, remains terminally rejected. ALGO materially underperformed E2160; ATOM's favourable point estimate failed the frozen dependence-aware lower-bound and 24H-delay gates. Markets passing were 0/2. No same-cohort rescue or correction of the nominated 2,160H policy is authorised.",
        "",
        "Issue #850 preregisters a distinct zero-grid variable-order suffix-transition candidate on ADAUSDT and LINKUSDT. It has not yet supplied eligible performance evidence and cannot modify this prospective epoch. Issue #851 separately freezes direct-representation family closure and likewise authorises no canonical change.",
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
    result["window"]["prior_cumulative_realized_hours"] = 578
    result["window"]["updated_cumulative_realized_hours"] = 579
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 847,
        "pull_request": 849,
        "family_id": "causal-historical-analog-consensus-abstention-1h-v1",
        "status": "terminal_rejection",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "correction_permitted": False,
        "markets_passing": 0,
        "markets_total": 2,
        "exact_head": "03aefd91130161d933ea6955fc189ca4a5974357",
        "workflow_run": 30684784277,
        "artifact_id": 8813522789,
        "artifact_sha256": "ce1d64d7b41a70f908b58f6600ba694d88069cde91f09b57db7e11ccd7a572b3",
        "evidence_sha256": "3db15fc8490f81dc21cf24a49bb99a19c78426ee0ab6e25459653734f77fc28e",
        "verdict": "reject_causal_historical_analog_consensus_abstention_1h_v1",
        "market_summary": {
            "ALGOUSDT": {"oos_net_return": 0.074788, "oos_sharpe": 0.3168, "e2160_oos_net_return": 0.931887, "delayed_oos_net_return": -0.110628, "gates_passed": 6, "gates_total": 12},
            "ATOMUSDT": {"oos_net_return": 0.612151, "oos_sharpe": 1.3921, "e2160_oos_net_return": -0.466201, "delayed_oos_net_return": -0.051384, "gates_passed": 10, "gates_total": 12},
        },
        "next_preregistered_issue": 850,
        "next_preregistered_family": "causal-variable-order-suffix-transition-long-cash-1h-v1",
        "family_closure_issue": 851,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the historical-analog architecture failed bilateral benchmark, dependence-aware uncertainty and delay gates; the separately preregistered suffix-transition candidate has not yet produced eligible frozen evidence",
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": "the new interval contains frozen long exposure" if exposed else "the new interval is cash-only and cannot validate conditional-long persistence",
    }
    result["next_strategy_action"] = "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation; keep the historical-analog candidate rejected, and permit no epoch restart unless the independently frozen variable-order suffix-transition candidate passes every bilateral gate and the direct-representation family closure does not reject its premise"
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
