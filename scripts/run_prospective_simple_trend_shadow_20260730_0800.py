from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260730_0700 as prior

HOUR_MS = prior.HOUR_MS
PREVIOUS_DECISION_HOUR_MS = 1_785_387_600_000  # 2026-07-30T05:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_391_200_000  # 2026-07-30T06:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_394_800_000  # 2026-07-30T07:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_398_400_000  # 2026-07-30T08:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_376_800_000  # 2026-07-30T02:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "da3fcf1c2ecccefd8f1d3f7ef0a484bbdc52bf4eec7866b12b7500942bc378a9"
PRIOR_ARTIFACT_SHA256 = "6b53ac21eb5173ce517ffe3cbe45c725b6752c4db810a4a8b9db89b7aa664ee0"


def configure_frozen_epoch() -> None:
    prior.PREVIOUS_DECISION_HOUR_MS = PREVIOUS_DECISION_HOUR_MS
    prior.REALIZED_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
    prior.PRIOR_REPORTED_SIGNAL_HOUR_MS = PRIOR_REPORTED_SIGNAL_HOUR_MS
    prior.LATEST_COMPLETE_SIGNAL_HOUR_MS = LATEST_COMPLETE_SIGNAL_HOUR_MS
    prior.RECENT_WINDOW_FIRST_DECISION_HOUR_MS = RECENT_WINDOW_FIRST_DECISION_HOUR_MS
    prior.RECENT_WINDOW_LAST_DECISION_HOUR_MS = RECENT_WINDOW_LAST_DECISION_HOUR_MS
    prior.PRIOR_RESULT_SHA256 = PRIOR_RESULT_SHA256
    prior.PRIOR_ARTIFACT_SHA256 = PRIOR_ARTIFACT_SHA256


def fmt_optional(value: float | None, digits: int = 4) -> str:
    return "undefined" if value is None else f"{value:.{digits}f}"


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow update through 08:00 UTC",
        "",
        f"- Generated: `{result['generated_at']}`",
        f"- Policy SHA-256: `{result['policy_sha256']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- New complete signal bars: `{result['window']['new_signal_bar_count']}`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        "- Canonical fee: `5 bps one-way`",
        "- Status: benchmark-shadow only; no paper/live authorisation",
        "",
        "| Market | Realised position | New target | Net return | Asset return | Residual | "
        "Turnover | Fee | Latest margin | Margin drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realised = market["realized_interval"]
        drift = market["signal_drift"]
        target = market["new_decisions"][0]["target"]
        lines.append(
            "| {instrument} | {position} | {target} | {net:.6%} | {asset:.6%} | "
            "{residual:.6%} | {turnover:.4f} | {fee:.6%} | {margin:.6%} | "
            "{margin_drift:+.6%} |".format(
                instrument=market["instrument"],
                position=realised["position"],
                target=target,
                net=realised["net_strategy_return"],
                asset=realised["asset_return"],
                residual=realised["strategy_residual_vs_buy_and_hold"],
                turnover=realised["turnover"],
                fee=realised["modeled_fee"],
                margin=drift["margin_at_latest_complete_signal_hour"],
                margin_drift=drift["margin_change"],
            )
        )

    lines.extend(
        [
            "",
            "## Five-interval forward scorecard",
            "",
            "| Market | Long decisions | Net return | Benchmark | Residual | Turnover | "
            "Fees | Edge/turnover | Max drawdown | Sharpe | Losses |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market in result["markets"]:
        recent = market["recent_forward_window"]
        edge = recent["edge_per_turnover_bps"]
        lines.append(
            "| {instrument} | {long}/{count} | {net:.6%} | {benchmark:.6%} | "
            "{residual:.6%} | {turnover:.4f} | {fees:.6%} | {edge} | "
            "{drawdown:.6%} | {sharpe} | {losses} |".format(
                instrument=market["instrument"],
                long=recent["long_decision_count"],
                count=recent["realized_interval_count"],
                net=recent["net_compound_return"],
                benchmark=recent["benchmark_compound_return"],
                residual=recent["residual_vs_buy_and_hold"],
                turnover=recent["turnover"],
                fees=recent["modeled_fees"],
                edge="undefined" if edge is None else f"{edge:.2f} bps",
                drawdown=recent["maximum_drawdown"],
                sharpe=fmt_optional(recent["sharpe"]),
                losses=recent["loss_count"],
            )
        )

    lines.extend(
        [
            "",
            "## Strategy-facing discrepancy diagnosis",
            "",
            result["strategy_facing_discrepancy"]["diagnosis"],
            "",
            "Issue #688 and closed draft PR #689 record terminal historical rejection evidence for "
            "the exact four-phase daily trend ensemble. This interval was not used to score, revise "
            "or rescue that family.",
            "",
            f"Verdict: `{result['verdict']}`",
            "",
            "No training-authorised correction was permitted or applied.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 534
    result["window"]["updated_cumulative_realized_hours"] = 535
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    latest_asset_returns = {
        market["instrument"]: market["realized_interval"]["asset_return"]
        for market in result["markets"]
    }
    five_interval_benchmarks = {
        market["instrument"]: market["recent_forward_window"]["benchmark_compound_return"]
        for market in result["markets"]
    }
    result["strategy_facing_discrepancy"] = {
        "classification": "latest_hour_opportunity_cost_vs_five_interval_loss_avoidance",
        "latest_interval_asset_returns": latest_asset_returns,
        "five_interval_benchmark_returns": five_interval_benchmarks,
        "diagnosis": (
            "Both assets rose in the newest realised hour while both five-interval buy-and-hold "
            "benchmarks remained negative. The frozen cash state therefore incurred one-hour "
            "opportunity cost but still delivered loss avoidance over the rolling five-interval "
            "window. This is horizon-dependent regime behaviour, not a chronology, next-open "
            "execution, policy-state or fee-accounting defect."
        ),
        "policy_or_accounting_defect_detected": False,
    }
    result["active_alpha_context"] = {
        "issue": 688,
        "pull_request": 689,
        "family_id": "exact-four-phase-daily-trend-ensemble-1h-v1",
        "status": "terminal_historical_rejection_evidence_closed_draft",
        "prospective_performance_consumed": False,
        "reason": (
            "the sole preregistered own-history four-phase trend ensemble produced favourable "
            "aggregate development-OOS point estimates near slow-trend boundary crossings, but "
            "both instruments failed the required profitable-fold breadth and all dependence-aware "
            "uncertainty lower bounds crossed zero; training performance was materially negative, "
            "ETH edge per turnover was slightly below B1, and the fractional-state effect was "
            "concentrated in only a small share of OOS hours, so this forward interval cannot alter "
            "phase count, phase hours, trend horizon, exposure mapping, cadence, fee model or "
            "market treatment"
        ),
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": (
            "the new interval contains frozen long exposure and therefore contributes "
            "conditional-long forward evidence"
            if exposed
            else "a cash-only new interval supplies no realised conditional-long return and "
            "therefore cannot validate historical selection persistence"
        ),
    }
    result["next_strategy_action"] = (
        "continue the identical frozen 2160H benchmark-shadow epoch at the next complete "
        "public 1H observation; do not prospectively rescue the rejected exact four-phase "
        "daily trend ensemble family"
    )
    base.write_outputs(output_dir, result)
    write_report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"),
    )
    args = parser.parse_args()
    result = run(args.output_dir, args.base_url.rstrip("/"))
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
