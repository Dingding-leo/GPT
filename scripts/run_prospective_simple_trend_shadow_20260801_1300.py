from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_1200 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_578_400_000
REALIZED_DECISION_HOUR_MS = 1_785_582_000_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_585_600_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_589_200_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_567_600_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "7e1969a85939533a4355e77945d0461b7138878de02a3d512947d60d0b247a98"
PRIOR_ARTIFACT_SHA256 = "8db035d0f48f1e5c34faaa2d0a14ae23ddc4a5477dcd759ef59ff9482aa35743"


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
        "# Prospective simple-trend shadow through 13:00 UTC on 1 August 2026",
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
    rejected = result["latest_terminal_candidate_context"]
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
            f"- Policy/accounting defect: `{drift['policy_or_accounting_defect_detected']}`",
            "",
            drift["diagnosis"],
            "",
            "## Strategy-correction disposition",
            "",
            f"Issue #{rejected['issue']} / PR #{rejected['pull_request']} rejected `{rejected['family_id']}` at the immutable public-source contract before performance. The fixed SOLUSDT source contained a partial UTC hour, so training, OOS and strategy metrics were not accessed.",
            "",
            f"Issue #{active['issue']} is the sole active performance-unseen architecture: `{active['family_id']}`. It evaluates ICXUSDT and ONTUSDT independently from each instrument's own lagged 1H sequence. This forward update consumes none of its OOS data and grants no correction authority.",
            "",
            "## Machine-readable verdict",
            "",
            "```json",
            json.dumps(
                {
                    "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
                    "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
                    "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
                    "candidate_verdict": rejected["verdict"],
                    "active_family_id": active["family_id"],
                    "active_family_status": active["status"],
                    "correction_permitted": result["training_authorized_correction"]["permitted"],
                    "correction_applied": result["training_authorized_correction"]["applied"],
                    "observation_epoch_restarted": result["training_authorized_correction"]["observation_epoch_restarted"],
                    "abort_triggered": result["abort_conditions"]["triggered"],
                    "verdict": result["verdict"],
                    "paper_trading_authorized": result["paper_trading_authorized"],
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
    result["window"]["prior_cumulative_realized_hours"] = 587
    result["window"]["updated_cumulative_realized_hours"] = 588
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["latest_terminal_candidate_context"] = {
        "issue": 879,
        "pull_request": 881,
        "family_id": "causal-stablecoin-quote-stress-entry-veto-1h-v1",
        "status": "terminal_source_contract_rejection_before_performance",
        "workflow_run": 30701895221,
        "tested_head": "a2d2bd8bdad3dc3cf8af3df7cacf0bd9539e9b66",
        "artifact_id": 8819081020,
        "artifact_sha256": "c908346c2f8a84c5e2b39bbffe5d89a5aa98d57a879eb35cd3a3f03418f381d4",
        "evidence_sha256": "e809aa22c139d2dbcaba02cca3c0c1d28b1bc75563f765d7f7408854f8084c9a",
        "candidate_count": 2,
        "parameter_grid_count": 0,
        "performance_accessed": False,
        "bootstrap_draws": 0,
        "markets_passing_all_gates": 0,
        "rejection_stage": "immutable_public_source_contract_before_performance",
        "source_failure": {
            "object": "SOLUSDT-1h-2023-03.zip",
            "hour_open": "2023-03-24T12:00:00Z",
            "observed_close": "2023-03-24T12:39:46.948Z",
            "observed_duration_seconds": 2386.949,
            "required_duration_seconds": 3600.0,
        },
        "verdict": "reject_causal_stablecoin_quote_stress_entry_veto_1h_v1",
        "correction_permitted": False,
    }
    result["active_alpha_context"] = {
        "issue": 882,
        "pull_request": None,
        "family_id": "causal-temporal-stochastic-dominance-trend-1h-v1",
        "classification": "executable_robust_slow_trend_representation_experiment",
        "status": "preregistered_active_performance_unseen",
        "candidate_count": 2,
        "diagnostic_count": 0,
        "parameter_grid_count": 0,
        "markets": ["ICXUSDT", "ONTUSDT"],
        "provider": "Binance public monthly SPOT archives",
        "signal": "Mann-Whitney temporal dominance over adjacent 1080H close blocks",
        "new_oos_consumed_by_this_forward_run": 0,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the stablecoin quote-stress candidate failed its immutable source contract before performance and the sole active temporal stochastic-dominance candidate remains performance-unseen",
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
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation and execute the unchanged ICX/ONT temporal stochastic-dominance architecture on its preregistered immutable cohort; restart an epoch only if both markets pass every frozen gate"
    )
    prior.prior.prior.rewrite_result(output_dir, result)
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
