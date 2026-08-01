from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_1500 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_589_200_000
REALIZED_DECISION_HOUR_MS = 1_785_592_800_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_596_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_600_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_578_400_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "0a86da5271ef6097f1a36b7df05e525ea7a0968c16910ad2b4b66646a18cdddc"
PRIOR_ARTIFACT_SHA256 = "0450015981847a5a1a234ce65f88faa22784c760449162a90f882575acbae161"


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
        "# Prospective simple-trend shadow through 16:00 UTC on 1 August 2026",
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
        f"Issue #{terminal['issue']} / PR #{terminal['pull_request']} terminally rejected `{terminal['family_id']}` at the immutable public-source contract before feature, training-performance or OOS access.",
        "",
        f"Issue #{active['issue']} is the sole active completed-evidence closure: `{active['family_id']}`. It introduces no candidates, market data, returns or OOS observations and cannot authorize a strategy correction by itself.",
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
    result["window"]["prior_cumulative_realized_hours"] = 590
    result["window"]["updated_cumulative_realized_hours"] = 591
    realised = result["markets"][0]["realized_interval"]
    result["window"]["realized_payoff_interval_start"] = realised["payoff_open_start"]
    result["window"]["realized_payoff_interval_end"] = realised["payoff_open_end"]
    total_intervals = sum(m["recent_forward_window"]["realized_interval_count"] for m in result["markets"])
    total_longs = sum(m["recent_forward_window"]["long_decision_count"] for m in result["markets"])
    signal_frequency = total_longs / total_intervals if total_intervals else None
    result["aggregate_forward_scorecard"] = {
        "market_count": len(result["markets"]),
        "realized_interval_count": total_intervals,
        "long_decision_count": total_longs,
        "signal_frequency": signal_frequency,
        "no_trade_frequency": None if signal_frequency is None else 1.0 - signal_frequency,
    }
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["latest_terminal_candidate_context"] = {
        "issue": 891,
        "pull_request": 893,
        "family_id": "causal-onchain-transaction-activity-confirmed-e2160-entry-1h-v1",
        "status": "terminal_source_contract_rejection_before_performance",
        "workflow_run": 30708866223,
        "tested_head": "7f057d8679f1797cd7f8973f962ab37dff41ef22",
        "artifact_id": 8821217482,
        "evidence_sha256": "4e036f804ef1efc9ba20845c18e9f07edf2cb629d63801ec9be26a9262658a38",
        "report_sha256": "62dd8c1253a9601d3fabd5c19eed96064041e8ee0cdeb1bfaf4b198639260392",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "performance_accessed": False,
        "training_metrics_computed": False,
        "oos_metrics_computed": False,
        "markets_passing_all_gates": 0,
        "source_failure": {
            "provider": "Coin Metrics Community",
            "asset": "doge",
            "metric": "TxCnt",
            "frequency": "1h",
            "http_status": 400,
            "response_body_sha256": "40a4a5ffb815160e10c7ee51e0dfe188dd19b6f021b91ab7c9a299d63b49e9f1",
        },
        "verdict": "reject_causal_onchain_transaction_activity_confirmed_e2160_entry_source_contract",
        "correction_permitted": False,
    }
    result["active_alpha_context"] = {
        "issue": 894,
        "pull_request": None,
        "family_id": "causal-public-same-asset-confirmation-channel-closure-1h-v1",
        "classification": "completed_evidence_strategy_family_closure",
        "status": "preregistered_active_zero_new_performance",
        "architecture_group_count": 2,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_oos_consumed": 0,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the on-chain transaction-activity candidate failed its frozen public-source contract before performance and the active same-asset confirmation-channel closure contains no executable correction",
    }
    exposed = any(m["realized_interval"]["position"] == 1 for m in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": "the new interval contains frozen long exposure" if exposed else "the new interval is cash-only and cannot validate conditional-long persistence",
    }
    result["next_strategy_action"] = (
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation and independently execute issue #894 exactly as frozen; do not restart an observation epoch unless a separately preregistered executable rule passes every predeclared gate"
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
