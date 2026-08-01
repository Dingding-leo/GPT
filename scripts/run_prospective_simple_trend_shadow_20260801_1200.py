from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_1100 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_574_800_000
REALIZED_DECISION_HOUR_MS = 1_785_578_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_582_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_585_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_564_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "9c7a4104835fb846cca413cdb267a0389f4993c504a9315cc573a29fa901488c"
PRIOR_ARTIFACT_SHA256 = "d5dc6a4a4e67b710b2c03139fdfb060b5ddf03561594c1a77affe68ecc58946e"


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
        "# Prospective simple-trend shadow through 12:00 UTC on 1 August 2026",
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
    closure = result["latest_family_closure_context"]
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
            "The completed lagged-BTC entry-gating family closure rejected all three preregistered architecture groups: zero groups were bilaterally superior to B1, dependence-supported, temporally broad, or state-transport supported. Same-cohort BTC stress-state rescues remain closed.",
            "",
            f"Closure artifact: `{closure['artifact_id']}` / `{closure['artifact_sha256']}`.",
            "",
            f"Issue #{active['issue']} is the sole active, performance-unseen strategy architecture: `{active['family_id']}`. It uses each target's own lagged sequence plus strictly lagged USDC-USDT 1H data; this forward run consumes none of its OOS data.",
            "",
            "## Machine-readable verdict",
            "",
            "```json",
            json.dumps(
                {
                    "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
                    "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
                    "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
                    "family_verdict": closure["verdict"],
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
    result["window"]["prior_cumulative_realized_hours"] = 586
    result["window"]["updated_cumulative_realized_hours"] = 587
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["latest_family_closure_context"] = {
        "issue": 877,
        "pull_request": 878,
        "family_id": "causal-lagged-btc-entry-gating-family-closure-1h-v1",
        "status": "terminal_rejection_exact_head_evidence_published",
        "workflow_run": 30700411497,
        "tested_head": "aebc76c933438ff4f5237c50bd0d86f0ed93c095",
        "artifact_id": 8818626935,
        "artifact_sha256": "3fe0cbf613617fc5d2350144283ebb97c6e68d3c0403585cbf33854ac16531ac",
        "evidence_sha256": "518228fb26fdbb455c2593790d6c47ca2bd94790d49c5b1f3b7afab889882a6d",
        "architecture_group_count": 3,
        "supportive_group_count": 0,
        "bilateral_positive_oos_groups": 1,
        "bilateral_benchmark_superior_groups": 0,
        "bilateral_positive_dependence_groups": 0,
        "bilateral_temporal_breadth_groups": 0,
        "bilateral_state_transport_groups": 0,
        "leave_one_group_out_support": 0,
        "new_candidate_count": 0,
        "new_oos_consumed": 0,
        "verdict": "reject_causal_lagged_btc_entry_gating_family",
    }
    result["active_alpha_context"] = {
        "issue": 879,
        "pull_request": None,
        "family_id": "causal-stablecoin-quote-stress-entry-veto-1h-v1",
        "classification": "executable_causal_exogenous_information_strategy",
        "status": "preregistered_active_performance_unseen",
        "candidate_count": 2,
        "diagnostic_count": 0,
        "parameter_grid_count": 0,
        "markets": ["SOLUSDT", "XRPUSDT"],
        "fixed_lagged_exogenous_series": "USDCUSDT",
        "new_oos_consumed_by_this_forward_run": 0,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the lagged-BTC entry-gating family is terminally rejected and the sole active stablecoin-quote candidate remains performance-unseen",
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
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation and execute the unchanged SOL/XRP stablecoin-quote-stress entry-veto architecture on its preregistered immutable cohort; restart an epoch only if both targets pass every bilateral gate"
    )
    prior.prior.rewrite_result(output_dir, result)
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
