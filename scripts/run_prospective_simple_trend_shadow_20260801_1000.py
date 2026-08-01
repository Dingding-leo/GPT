from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260801_0900 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_567_600_000
REALIZED_DECISION_HOUR_MS = 1_785_571_200_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_574_800_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_578_400_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_556_800_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "faa8d0dc43096585a689e5270d01b4cb24bd6780c4a10ae4f349485a601ecba0"
PRIOR_ARTIFACT_SHA256 = "717c6516a052f77c16b4b2925a4a03672ed61a711e3ca2181712e749792f5bcd"


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


def rewrite_result(output_dir: Path, result: dict[str, Any]) -> None:
    payload = (
        json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    ).encode()
    (output_dir / "result.json").write_bytes(payload)
    (output_dir / "result.sha256").write_text(hashlib.sha256(payload).hexdigest() + "\n")


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow through 10:00 UTC on 1 August 2026",
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
    alpha = result["active_alpha_context"]
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
            "The sole active strategy architecture is the preregistered `causal-week-phase-deseasonalized-endpoint-trend-1h-v1` experiment on SUSHI-USDT and CRV-USDT. Its market set, 28 UTC week phases, calibration interval, 2,160H horizon, daily next-open execution, exact 5 bps one-way fee and bilateral gates were frozen before performance access.",
            "",
            "This prospective BTC/ETH observation neither consumes that experiment's OOS data nor authorises a correction. The nominated policy remains immutable unless the separate architecture passes every frozen gate independently in both markets; otherwise it must be rejected without same-cohort rescue.",
            "",
            "## Machine-readable verdict",
            "",
            "```json",
            json.dumps(
                {
                    "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
                    "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
                    "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
                    "active_family_id": alpha["family_id"],
                    "active_family_status": alpha["status"],
                    "active_candidate_count": alpha["candidate_count"],
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
    result["window"]["prior_cumulative_realized_hours"] = 584
    result["window"]["updated_cumulative_realized_hours"] = 585
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 866,
        "pull_request": None,
        "family_id": "causal-week-phase-deseasonalized-endpoint-trend-1h-v1",
        "classification": "executable_base_signal_representation_experiment",
        "status": "preregistered_active_performance_unseen",
        "candidate_count": 2,
        "diagnostic_count": 0,
        "parameter_grid_count": 0,
        "markets": ["SUSHI-USDT", "CRV-USDT"],
        "markets_required": 2,
        "markets_passing_all_gates": 0,
        "correction_permitted": False,
        "new_oos_consumed_by_this_forward_run": 0,
        "canonical_mutation_permitted": False,
        "verdict": "pending_frozen_bilateral_evaluation",
        "open_hypothesis_path": "training-frozen 28-phase UTC week-profile removal may improve the own-instrument 2160H endpoint trend without excess turnover",
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the sole active architecture is preregistered but performance-unseen; no bilateral gate result exists and this forward observation cannot authorise a correction",
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
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation; separately execute the unchanged week-phase-deseasonalized SUSHI/CRV architecture from issue 866, and permit a new frozen epoch only if both markets pass every predeclared gate"
    )
    rewrite_result(output_dir, result)
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
