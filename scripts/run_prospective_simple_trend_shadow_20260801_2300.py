from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_2200 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_614_400_000
REALIZED_DECISION_HOUR_MS = 1_785_618_000_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_621_600_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_625_200_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_603_600_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "5edadced042f2fbf6e313d4c6e0b4ab5786b365c2f651dc6cd39f95034e9d9af"
PRIOR_ARTIFACT_SHA256 = "ab65c9eb98d4053571961126fade1720017fa992a2c41bc1d6491b462ff80512"


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
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    (output_dir / "result.json").write_text(payload)
    (output_dir / "result.sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "\n"
    )


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow through 23:00 UTC on 1 August 2026",
        "",
        f"- Policy: `{result['policy_name']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- Latest complete signal bar: `{result['window']['latest_complete_signal_bar_start']}`",
        f"- Realised payoff interval: `{result['window']['realized_payoff_interval_start']}` to `{result['window']['realized_payoff_interval_end']}`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Abort: `{result['abort_conditions']['triggered']}`",
        "",
        "| Market | Position | New target | Expected net | Realised net | Benchmark | Residual | Turnover | Fees | 2160H margin | Margin drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realised = market["realized_interval"]
        decision = market["new_decisions"][0]
        lines.append(
            f"| {market['instrument']} | {'Long' if realised['position'] else 'Cash'} | "
            f"{'Long' if decision['target'] else 'Cash'} | "
            f"{pct(realised['expected_net_return_under_frozen_decision'])} | "
            f"{pct(realised['net_strategy_return'])} | {pct(realised['asset_return'])} | "
            f"{pct(realised['strategy_residual_vs_buy_and_hold'])} | {realised['turnover']} | "
            f"{pct(realised['modeled_fee'])} | {pct(decision['margin'])} | "
            f"{pct(market['discrepancy_diagnosis']['signal_margin_change'])} |"
        )

    lines.extend(
        [
            "",
            "## Five-interval scorecard",
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
            else f"{recent['edge_per_turnover_bps']:.6f} bps"
        )
        lines.append(
            f"| {market['instrument']} | {recent['long_decision_count']}/{recent['realized_interval_count']} | "
            f"{pct(recent['net_compound_return'])} | {pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | {sharpe} | {edge} |"
        )

    drift = result["strategy_facing_discrepancy"]
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
            "Issue #931 / PR #932 terminally rejected the frozen ADA-USDT/DOT-USDT volatility-normalized first-passage consensus architecture before target-return or sealed-OOS access. Both public 1H source arms passed, but both training-support arms failed temporal transport: ADA's largest disagreement quarter contributed 47.89% against a 40% maximum; DOT had no 2024-Q1 disagreements, 80.77% in one direction and 60.26% in one quarter.",
            "",
            "Issue #933 is the sole active completed-evidence event-clock/renewal-timing family closure. It has zero candidates, zero new market data, zero target returns and zero OOS authority.",
            "",
            "```json",
            json.dumps(result["machine_readable_verdict"], sort_keys=True, indent=2),
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
    result["window"]["prior_cumulative_realized_hours"] = 597
    result["window"]["updated_cumulative_realized_hours"] = 598
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
        "issue": 931,
        "pull_request": 932,
        "family_id": "causal-volatility-normalized-first-passage-consensus-trend-1h-v1",
        "status": "terminal_bilateral_training_support_rejection_before_performance_or_oos",
        "workflow_run": 30724659548,
        "tested_head": "88e244d0f9d276c9d5b42ecc9ecd930ae1bb3632",
        "artifact_id": 8825942016,
        "artifact_sha256": "efea813e5d5ac64f0d142f0b24bc774629ca4fe050d7f954349f1aeacfac0ef1",
        "evidence_sha256": "ca85ad5e2ff677c787d8ba53489f3dcde3ed7f2b9d1d44643edfd4df4dc45432",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "source_arms_passing": 2,
        "source_arm_count": 2,
        "training_support_arms_passing": 0,
        "training_support_arm_count": 2,
        "performance_accessed": False,
        "oos_accessed": False,
        "verdict": "reject_causal_volatility_normalized_first_passage_consensus_trend_1h_v1",
        "correction_permitted": False,
    }
    result["active_alpha_context"] = {
        "issue": 933,
        "pull_request": None,
        "family_id": "causal-own-price-event-clock-renewal-timing-family-closure-1h-v1",
        "classification": "completed_evidence_strategy_family_closure",
        "status": "preregistered_active_evidence_only_no_new_data_returns_or_oos",
        "architecture_group_count": 4,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_target_returns": 0,
        "new_oos_consumed": 0,
        "performance_seen": False,
        "oos_accessed": False,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the first-passage consensus candidate failed both frozen training-support arms "
            "before target-return or sealed-OOS access, and issue #933 is evidence-only"
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
        "observation and execute issue #933's completed-evidence event-clock/renewal-timing family "
        "closure exactly as frozen; create no correction or new observation epoch because the "
        "latest candidate failed bilateral training support before economics"
    )
    result["machine_readable_verdict"] = {
        "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
        "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
        "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
        "signal_frequency": result["aggregate_forward_scorecard"]["signal_frequency"],
        "no_trade_frequency": result["aggregate_forward_scorecard"]["no_trade_frequency"],
        "terminal_candidate_verdict": result["latest_terminal_candidate_context"]["verdict"],
        "terminal_candidate_training_support_arms_passing": 0,
        "terminal_candidate_performance_accessed": False,
        "terminal_candidate_oos_accessed": False,
        "active_family_id": result["active_alpha_context"]["family_id"],
        "active_family_status": result["active_alpha_context"]["status"],
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
