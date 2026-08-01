from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_1400 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_585_600_000
REALIZED_DECISION_HOUR_MS = 1_785_589_200_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_592_800_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_596_400_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_574_800_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "293798abce5f3a0d6876926248032ceb7c19319a6b3013cb4f549ebd9fa1477d"
PRIOR_ARTIFACT_SHA256 = "d49b22074c08f22886e9bf485e92bbc12c68d7b2da8f491b876f9cc80a67b5e4"


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


def write_json(output_dir: Path, result: dict[str, Any]) -> None:
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False).encode("utf-8") + b"\n"
    (output_dir / "result.json").write_bytes(payload)
    (output_dir / "result.sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n")


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow through 15:00 UTC on 1 August 2026",
        "",
        f"- Policy: `{result['policy_name']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- Latest complete signal bar: `{result['window']['latest_complete_signal_bar_start']}`",
        f"- Realised payoff interval: `{result['window']['realized_payoff_interval_start']}` to `{result['window']['realized_payoff_interval_end']}`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Abort: `{result['abort_conditions']['triggered']}`",
        "",
        "| Market | Position | New target | Net | Benchmark | Residual | Turnover | Fees | 2160H margin | Margin drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realised = market["realized_interval"]
        decision = market["new_decisions"][0]
        lines.append(
            f"| {market['instrument']} | {'Long' if realised['position'] else 'Cash'} | "
            f"{'Long' if decision['target'] else 'Cash'} | {pct(realised['net_strategy_return'])} | "
            f"{pct(realised['asset_return'])} | {pct(realised['strategy_residual_vs_buy_and_hold'])} | "
            f"{realised['turnover']} | {pct(realised['modeled_fee'])} | {pct(decision['margin'])} | "
            f"{pct(market['discrepancy_diagnosis']['signal_margin_change'])} |"
        )
    lines.extend([
        "",
        "## Five-interval forward scorecard",
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
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | {pct(recent['modeled_fees'])} | "
            f"{pct(recent['maximum_drawdown'])} | {sharpe} | {edge} |"
        )
    drift = result["strategy_facing_discrepancy"]
    terminal = result["latest_terminal_candidate_context"]
    active = result["active_alpha_context"]
    verdict = {
        "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
        "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
        "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
        "signal_frequency": result["aggregate_forward_scorecard"]["signal_frequency"],
        "no_trade_frequency": result["aggregate_forward_scorecard"]["no_trade_frequency"],
        "terminal_candidate_verdict": terminal["verdict"],
        "active_family_id": active["family_id"],
        "active_family_status": active["status"],
        "correction_permitted": result["training_authorized_correction"]["permitted"],
        "correction_applied": result["training_authorized_correction"]["applied"],
        "observation_epoch_restarted": result["training_authorized_correction"]["observation_epoch_restarted"],
        "abort_triggered": result["abort_conditions"]["triggered"],
        "verdict": result["verdict"],
        "paper_trading_authorized": result["paper_trading_authorized"],
        "live_trading_authorized": result["live_trading_authorized"],
    }
    lines.extend([
        "",
        "## Drift diagnosis",
        "",
        f"- Instrument: `{drift['selected_instrument']}`",
        f"- Classification: `{drift['classification']}`",
        f"- Latest benchmark: `{pct(drift['latest_interval_asset_return'])}`",
        f"- Five-interval benchmark: `{pct(drift['five_interval_benchmark_return'])}`",
        f"- Margin drift: `{pct(drift['trend_margin_drift'])}`",
        f"- Policy/accounting defect detected: `{drift['policy_or_accounting_defect_detected']}`",
        "",
        drift["diagnosis"],
        "",
        "## Candidate and correction disposition",
        "",
        f"Issue #{terminal['issue']} / PR #{terminal['pull_request']} rejected `{terminal['family_id']}` before sealed OOS performance because the training-only confirmation gate produced zero vetoes in both fixed sleeves.",
        "",
        f"Issue #{active['issue']} is the sole active, performance-unseen architecture: `{active['family_id']}`. It uses lagged same-asset Coin Metrics transaction counts only as an entry veto and consumed no OOS information in this forward update.",
        "",
        "```text",
        f"Correction permitted          {str(result['training_authorized_correction']['permitted']).lower()}",
        f"Correction applied            {str(result['training_authorized_correction']['applied']).lower()}",
        f"Policy changed                {str(result['training_authorized_correction']['policy_changed']).lower()}",
        f"Observation epoch restarted   {str(result['training_authorized_correction']['observation_epoch_restarted']).lower()}",
        "```",
        "",
        "## Machine-readable verdict",
        "",
        "```json",
        json.dumps(verdict, sort_keys=True, indent=2),
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
    result["window"]["prior_cumulative_realized_hours"] = 589
    result["window"]["updated_cumulative_realized_hours"] = 590
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["latest_terminal_candidate_context"] = {
        "issue": 889,
        "pull_request": 890,
        "family_id": "causal-same-asset-composite-index-confirmed-e2160-entry-1h-v1",
        "status": "terminal_training_support_rejection_before_oos",
        "workflow_run": 30706543671,
        "tested_head": "15c7fdebe09f3c4ae8f5e7971f8f9f5b03cd4eb6",
        "artifact_id": 8820561525,
        "artifact_sha256": "2f3542bbbaa27a77c4e3cecbb35abc44164d86de1291e7b3b4fa58d742396672",
        "evidence_sha256": "15f0fab0b62fdb41b3c7436cbf6ef0af4fd8ba6eeb1d01570123d69d94581a3a",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "performance_accessed": False,
        "markets_passing_all_gates": 0,
        "training_veto_counts": {"DOGE-USDT": 0, "LTC-USDT": 0},
        "verdict": "reject_causal_same_asset_composite_index_confirmed_e2160_entry_1h_v1",
        "correction_permitted": False,
    }
    result["active_alpha_context"] = {
        "issue": 891,
        "pull_request": None,
        "family_id": "causal-onchain-transaction-activity-confirmed-e2160-entry-1h-v1",
        "classification": "executable_causal_exogenous_information_strategy",
        "status": "preregistered_active_performance_unseen",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "target_markets": ["DOGE-USDT", "LTC-USDT"],
        "lagged_exogenous_series": ["coinmetrics:doge:TxCnt:1h", "coinmetrics:ltc:TxCnt:1h"],
        "new_market_data_consumed_by_this_forward_run": 0,
        "new_oos_consumed_by_this_forward_run": 0,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the same-asset index confirmation candidate failed its frozen training-only information-support gate and the on-chain transaction-activity candidate remains preregistered and performance-unseen",
    }
    exposed = any(m["realized_interval"]["position"] == 1 for m in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": "the new interval contains frozen long exposure" if exposed else "the new interval is cash-only and cannot validate conditional-long persistence",
    }
    result["next_strategy_action"] = (
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation and independently execute issue #891 exactly as frozen; permit a new observation epoch only if both on-chain-confirmed sleeves pass every predeclared source, support, performance, breadth, uncertainty and delay gate"
    )
    write_json(output_dir, result)
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
