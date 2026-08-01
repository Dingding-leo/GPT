from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_1600 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_592_800_000
REALIZED_DECISION_HOUR_MS = 1_785_596_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_600_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_603_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_582_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "84c07df22e7171531c90fb9271b9dfc6a9a373893b09a6f28c5647e2949099bd"
PRIOR_ARTIFACT_SHA256 = "dc79d744c1a3fdad19d032aa136dd52edb215c5bf6bf293d6a827e4c04c8b97b"


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
        "# Prospective simple-trend shadow through 17:00 UTC on 1 August 2026",
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
    lines.extend(
        [
            "",
            "## Five-interval forward scorecard",
            "",
            "| Market | Longs | Net | Benchmark | Residual | Turnover | Fees | Max DD | Sharpe | Edge/turnover |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market in result["markets"]:
        recent = market["recent_forward_window"]
        sharpe = "undefined" if recent["sharpe"] is None else f"{recent['sharpe']:.6f}"
        edge = (
            "undefined"
            if recent["edge_per_turnover_bps"] is None
            else f"{recent['edge_per_turnover_bps']:.6f}"
        )
        lines.append(
            f"| {market['instrument']} | {recent['long_decision_count']}/{recent['realized_interval_count']} | "
            f"{pct(recent['net_compound_return'])} | {pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | {sharpe} | {edge} |"
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
        "observation_epoch_restarted": result["training_authorized_correction"][
            "observation_epoch_restarted"
        ],
        "abort_triggered": result["abort_conditions"]["triggered"],
        "verdict": result["verdict"],
        "paper_trading_authorized": result["paper_trading_authorized"],
        "live_trading_authorized": result["live_trading_authorized"],
    }
    lines.extend(
        [
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
            f"Issue #{terminal['issue']} / PR #{terminal['pull_request']} terminally rejected "
            f"`{terminal['family_id']}` with 0/2 markets passing. COMP timing was destructive; "
            "LINK's favourable point estimate lacked dependence-aware, breadth and bilateral support.",
            "",
            f"Issue #{active['issue']} is the sole active performance-unseen architecture: "
            f"`{active['family_id']}` on APTUSDT and LDOUSDT independently. This forward update "
            "consumes none of its training or OOS performance.",
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
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 591
    result["window"]["updated_cumulative_realized_hours"] = 592
    realised = result["markets"][0]["realized_interval"]
    result["window"]["realized_payoff_interval_start"] = realised["payoff_open_start"]
    result["window"]["realized_payoff_interval_end"] = realised["payoff_open_end"]

    total_intervals = sum(
        market["recent_forward_window"]["realized_interval_count"] for market in result["markets"]
    )
    total_longs = sum(
        market["recent_forward_window"]["long_decision_count"] for market in result["markets"]
    )
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
        "issue": 897,
        "pull_request": 899,
        "family_id": "causal-bocpd-duration-confirmed-e2160-entry-1h-v1",
        "status": "terminal_bilateral_rejection",
        "workflow_run": 30711305929,
        "tested_head": "4c0fddf698bd9a0cb79c7312c8b201dec2c20ccb",
        "artifact_id": 8821978012,
        "artifact_sha256": "3ebb9ae7cc7249214ebd2abebb047d64087c87b9a0d7b0c65f89c3534d25c01c",
        "evidence_sha256": "7d1dd9e5fadfc4674f79317dd8882c389d5ec8004ac26c5f97c9ff99a4386315",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "performance_accessed": True,
        "markets_passing_all_gates": 0,
        "market_summary": {
            "COMPUSDT": {
                "candidate_oos_net_return": -0.238538,
                "candidate_oos_sharpe": -0.2998,
                "e2160_oos_net_return": -0.125652,
                "e2160_oos_sharpe": 0.2229,
            },
            "LINKUSDT": {
                "candidate_oos_net_return": 0.417411,
                "candidate_oos_sharpe": 0.6878,
                "e2160_oos_net_return": 0.131387,
                "e2160_oos_sharpe": 0.4789,
            },
        },
        "verdict": "reject_causal_bocpd_duration_confirmed_e2160_entry_1h_v1",
        "correction_permitted": False,
    }
    result["active_alpha_context"] = {
        "issue": 901,
        "pull_request": None,
        "family_id": "causal-trade-count-clock-endpoint-trend-1h-v1",
        "classification": "zero_grid_executable_temporal_representation_experiment",
        "status": "preregistered_active_performance_unseen",
        "markets": ["APTUSDT", "LDOUSDT"],
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "performance_seen": False,
        "oos_accessed": False,
        "new_market_data_in_forward_update": 0,
        "new_oos_consumed_in_forward_update": 0,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the BOCPD duration-confirmed candidate failed bilateral gates and the sole active "
            "trade-count-clock architecture remains preregistered and performance-unseen"
        ),
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": (
            "the new interval contains frozen long exposure"
            if exposed
            else "the new interval is cash-only and cannot validate conditional-long persistence"
        ),
    }
    result["next_strategy_action"] = (
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H "
        "observation and execute issue #901 separately exactly as frozen; restart no observation "
        "epoch unless both APTUSDT and LDOUSDT pass every predeclared source, support, economic, "
        "uncertainty, breadth, turnover and delay gate"
    )
    write_json(output_dir, result)
    write_report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com")
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.output_dir, args.base_url.rstrip("/")),
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
