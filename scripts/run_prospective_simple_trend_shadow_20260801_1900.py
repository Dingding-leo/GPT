from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_1800 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_600_000_000
REALIZED_DECISION_HOUR_MS = 1_785_603_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_607_200_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_610_800_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_589_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "63bc66481c8fda3f1242639faa820ff2d523900874e3418d1090a94ad5e6edee"
PRIOR_ARTIFACT_SHA256 = "68750e83030acbd7f894bac8e6ee2df2fc3afc3285245160c7eb6caa52539fd5"


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
        "# Prospective simple-trend shadow through 19:00 UTC on 1 August 2026",
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
            f"Issue #{terminal['issue']} / PR #{terminal['pull_request']} rejected "
            f"`{terminal['family_id']}` at the bilateral training-support gate before OOS or "
            "performance access. The feature varied numerically in both markets, but only AVAX "
            "altered any entry decisions and its support remained below the frozen breadth and "
            "deferred-entry minimums.",
            "",
            f"Issue #{active['issue']} is the sole active completed-evidence architecture: "
            f"`{active['family_id']}`. It consumes no new market data or OOS and can only close "
            "the aggregate-participation information family.",
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
    result["window"]["prior_cumulative_realized_hours"] = 593
    result["window"]["updated_cumulative_realized_hours"] = 594
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
        "issue": 907,
        "pull_request": 908,
        "family_id": "causal-range-impact-liquidity-confirmed-e2160-entry-1h-v1",
        "status": "terminal_training_support_rejection_before_performance",
        "workflow_run": 30715040930,
        "tested_head": "ea0a2abe5277da4bb2a41a2e1044fe0d99b95f1a",
        "artifact_id": 8823076798,
        "artifact_sha256": "c0bf18845781e0ba5bce8f4b984773b08e802360349467bb4b3739c0ab466081",
        "evidence_sha256": "d879a9c8965ff9dd4d2e3c75166cb8be981e4d6afe681f9aba7f6f917f1f08fc",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "source_objects_verified": 132,
        "source_objects_expected": 132,
        "performance_accessed": False,
        "oos_accessed": False,
        "markets_passing_all_gates": 0,
        "support_summary": {
            "AVAXUSDT": {
                "valid_training_decisions": 270,
                "distinct_feature_values": 270,
                "feature_iqr": 0.0001236469947459923,
                "entry_vetoes": 18,
                "veto_quarters": 2,
                "later_authorized_entries": 13,
            },
            "FILUSDT": {
                "valid_training_decisions": 270,
                "distinct_feature_values": 270,
                "feature_iqr": 0.00004258388772664318,
                "entry_vetoes": 0,
                "veto_quarters": 0,
                "later_authorized_entries": 0,
            },
        },
        "verdict": "reject_causal_range_impact_liquidity_confirmed_e2160_entry_1h_v1",
        "correction_permitted": False,
    }
    result["active_alpha_context"] = {
        "issue": 909,
        "pull_request": None,
        "family_id": "causal-aggregate-participation-information-family-closure-1h-v1",
        "classification": "completed_evidence_architecture_family_closure",
        "status": "preregistered_active_no_new_performance_access",
        "architecture_groups": 3,
        "markets": ["APTUSDT", "LDOUSDT", "ATOMUSDT", "NEARUSDT", "AVAXUSDT", "FILUSDT"],
        "candidate_count": 0,
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
            "the range-impact candidate failed its frozen bilateral training-support gate before "
            "OOS access, while issue #909 is an evidence-only family closure with zero candidates"
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
        "observation and complete issue #909 exactly as frozen; restart no observation epoch "
        "because the active family closure has zero executable candidates and cannot authorize a "
        "strategy correction"
    )
    result["machine_readable_verdict"] = {
        "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
        "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
        "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
        "signal_frequency": result["aggregate_forward_scorecard"]["signal_frequency"],
        "no_trade_frequency": result["aggregate_forward_scorecard"]["no_trade_frequency"],
        "terminal_candidate_verdict": result["latest_terminal_candidate_context"]["verdict"],
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
    prior.write_json(output_dir, result)
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
