from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_2300 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_618_000_000
REALIZED_DECISION_HOUR_MS = 1_785_621_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_625_200_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_628_800_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_607_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "b2245342de9799670c01a72b45e717fe7ebb16d96027d3bfd9e4ce9539833ad0"
PRIOR_ARTIFACT_SHA256 = "17f4ec4919d3ea2a921bf37a8b7138138abab2cadf6ef70baa9af0f7092f6c9a"


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
        "# Prospective simple-trend shadow through 00:00 UTC on 2 August 2026",
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
            "Issue #936 / PR #937 rejected the frozen forward-minus-realised volatility-premium diagnostic at the immutable target-grid gate. Both authenticated Binance target archives contained the same 12 missing UTC hours, so no feature, opportunity label, return or sealed-OOS result was accessed.",
            "",
            "Issue #938 is the sole active source-contract-first architecture. It may prove or reject a fixed six-arm public 1H same-asset venue-volume panel only; it has zero candidates and no target-return authority.",
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
    result["window"]["prior_cumulative_realized_hours"] = 598
    result["window"]["updated_cumulative_realized_hours"] = 599
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
        "issue": 936,
        "pull_request": 937,
        "family_id": "causal-forward-realized-volatility-premium-opportunity-diagnostic-1h-v1",
        "status": "terminal_bilateral_immutable_target_grid_rejection_before_feature_or_performance",
        "workflow_run": 30725643854,
        "tested_head": "8e2d0c7b2b00ce19a4139ef2a890afcff237f7c1",
        "artifact_id": 8826250064,
        "artifact_sha256": "0810df74d1fe6d5c03f13e057a1ea100ab5a51f8ba6ee0bbcb3b95ebbb42ae99",
        "evidence_sha256": "3b5edf30c9abdc9b2d251d285eae5686d3feeb829232bae11d862d83957579f1",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "source_arms_passing": 0,
        "source_arm_count": 2,
        "missing_hours_per_target": 12,
        "performance_accessed": False,
        "oos_accessed": False,
        "verdict": "reject_causal_forward_realized_volatility_premium_opportunity_diagnostic_1h_v1",
        "correction_permitted": False,
    }
    result["active_alpha_context"] = {
        "issue": 938,
        "pull_request": None,
        "family_id": "causal-same-asset-venue-fragmentation-source-contract-1h-v1",
        "classification": "source_contract_first_materially_orthogonal_market_structure_experiment",
        "status": "preregistered_active_source_only_no_feature_returns_or_oos",
        "source_arm_count": 6,
        "candidate_count": 0,
        "parameter_grid_count": 0,
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
            "the latest diagnostic failed its immutable bilateral target-grid gate before "
            "feature or performance access, while issue #938 is source-contract-only"
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
        "observation and execute issue #938 strictly as a six-arm source-only feasibility test; "
        "define no venue-fragmentation feature and access no target return unless every frozen "
        "source gate passes"
    )
    result["machine_readable_verdict"] = {
        "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
        "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
        "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
        "signal_frequency": result["aggregate_forward_scorecard"]["signal_frequency"],
        "no_trade_frequency": result["aggregate_forward_scorecard"]["no_trade_frequency"],
        "terminal_candidate_verdict": result["latest_terminal_candidate_context"]["verdict"],
        "terminal_candidate_source_arms_passing": 0,
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
