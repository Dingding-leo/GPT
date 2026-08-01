from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_0700 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_560_400_000
REALIZED_DECISION_HOUR_MS = 1_785_564_000_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_567_600_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_571_200_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_549_600_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "37a9727ebc51a58ae1a5c80758ed8b5b5fe51bfb56c4315b27d6973d4843350d"
PRIOR_ARTIFACT_SHA256 = "f15a4ba1646e711382bc1fd6df6ccb1f81abc90e00177e79d2f552236e456df5"


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
        "# Prospective simple-trend shadow through 08:00 UTC on 1 August 2026",
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
            else f"{recent['edge_per_turnover_bps']:.6f}"
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
            f"- Policy/accounting defect: `{drift['policy_or_accounting_defect_detected']}`",
            "",
            drift["diagnosis"],
            "",
            "## Strategy-correction disposition",
            "",
            "The completed `causal-microstructure-resilience-family-closure-1h-v1` audit terminally rejects the resilience/absorption family. Across four frozen information groups it found 0/4 supportive groups, 0/4 dependence-aware passes, 1/4 temporal-breadth passes and 0/4 replication-or-latency passes. Every leave-one-group-out audit retained zero supportive groups. No new candidate, market data, OOS interval, parameter search, filtering or sign reversal was consumed.",
            "",
            "The closure confirms that aggregate taker flow, individual-trade flow/price residuals, onset-only aggressive-flow absorption and L2 bid replenishment do not authorise a frozen-policy correction. Same-family threshold, window, smoothing, nonlinear relabelling and market-subset rescue are closed.",
            "",
            "## Machine-readable verdict",
            "",
            "```json",
            json.dumps(
                {
                    "latest_complete_signal_bar_start": result["window"][
                        "latest_complete_signal_bar_start"
                    ],
                    "updated_cumulative_realized_hours": result["window"][
                        "updated_cumulative_realized_hours"
                    ],
                    "canonical_fee_bps_one_way": result[
                        "canonical_fee_bps_one_way"
                    ],
                    "candidate_verdict": result["active_alpha_context"]["verdict"],
                    "candidate_markets_passing": result["active_alpha_context"][
                        "markets_passing_all_gates"
                    ],
                    "correction_permitted": result["training_authorized_correction"][
                        "permitted"
                    ],
                    "correction_applied": result["training_authorized_correction"][
                        "applied"
                    ],
                    "observation_epoch_restarted": result[
                        "training_authorized_correction"
                    ]["observation_epoch_restarted"],
                    "abort_triggered": result["abort_conditions"]["triggered"],
                    "verdict": result["verdict"],
                    "paper_trading_authorized": result[
                        "paper_trading_authorized"
                    ],
                    "live_trading_authorized": result["live_trading_authorized"],
                },
                sort_keys=True,
                indent=2,
            ),
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
    result["window"]["prior_cumulative_realized_hours"] = 582
    result["window"]["updated_cumulative_realized_hours"] = 583
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 861,
        "pull_request": 863,
        "family_id": "causal-microstructure-resilience-family-closure-1h-v1",
        "classification": "completed_evidence_architecture_family_closure",
        "status": "terminal_rejection",
        "candidate_count": 0,
        "diagnostic_count": 0,
        "parameter_grid_count": 0,
        "markets_passing_all_gates": 0,
        "correction_permitted": False,
        "exact_head": "6a80e38f6e132cabaf3338d30975f7f3c4b2adf0",
        "workflow_run": 30692279202,
        "artifact_id": 8816068422,
        "artifact_sha256": "5630645f18f5f5064a6c82eaefc40b4d688cf88ab8ea9674d3bc7bdc22b088d0",
        "evidence_sha256": "1aa3fa4261e8f6f4246fd9ccd90ed5ab054ba1d2770f06651be1efad9a9d563b",
        "architecture_group_count": 4,
        "supportive_group_count": 0,
        "dependence_aware_support_count": 0,
        "temporal_breadth_pass_count": 1,
        "replication_or_latency_pass_count": 0,
        "source_executable_count": 3,
        "leave_one_group_out_min_supportive": 0,
        "new_market_data_acquired": 0,
        "new_oos_consumed": 0,
        "verdict": "reject_causal_microstructure_resilience_family",
        "open_hypothesis_path": "materially different same-instrument temporal information architectures outside resilience/absorption",
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the completed microstructure-resilience family closure found zero supportive groups and failed every family acceptance gate; no executable correction is authorised",
    }
    exposed = any(
        market["realized_interval"]["position"] == 1 for market in result["markets"]
    )
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": (
            "the new interval contains frozen long exposure"
            if exposed
            else "the new interval is cash-only and cannot validate conditional-long persistence"
        ),
    }
    result["next_strategy_action"] = (
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation; keep the microstructure-resilience family closed, and preregister any materially different same-instrument temporal architecture before accessing its performance"
    )
    prior.base.write_outputs(output_dir, result)
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
