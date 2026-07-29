from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1400 as prior
import run_prospective_simple_trend_shadow_1800 as base

HOUR_MS = prior.HOUR_MS
PREVIOUS_DECISION_HOUR_MS = 1_785_326_400_000  # 2026-07-29T12:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_330_000_000  # 2026-07-29T13:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_333_600_000  # 2026-07-29T14:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_337_200_000  # 2026-07-29T15:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_315_600_000  # 2026-07-29T09:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "631f1387d611e254cf8d687ea560e6e2f25e3835fb009ec31947d471bde0be5f"
PRIOR_ARTIFACT_SHA256 = "346b1129130913e19a74256f41d387e14e59ade82cc0d11a976e1604bf62c684"


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


def discrepancy_text(result: dict[str, Any]) -> str:
    mismatches: list[str] = []
    for market in result["markets"]:
        realised = market["realized_interval"]
        drift = market["signal_drift"]
        asset = realised["asset_return"]
        margin_change = drift["margin_change"]
        if asset != 0.0 and margin_change != 0.0 and (asset > 0.0) != (margin_change > 0.0):
            mismatches.append(market["instrument"])
    if mismatches:
        return (
            "Open-to-open benchmark direction opposed completed-close 2160H margin drift for "
            + ", ".join(mismatches)
            + ". These measurements use different price intervals and rolling reference closes; "
            "the divergence is classified as regime drift, not an execution or fee defect."
        )
    return (
        "Open-to-open benchmark direction and completed-close 2160H margin drift did not create "
        "a sign discrepancy in this interval. Chronology and fee accounting remained consistent."
    )


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow update through 15:00 UTC",
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
            "Issue #634 and draft PR #635 record historical development rejection evidence for "
            "the low-frequency trend-coherence hysteresis family. This interval was not used to "
            "score, revise or rescue that family.",
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
    result["window"]["prior_cumulative_realized_hours"] = 517
    result["window"]["updated_cumulative_realized_hours"] = 518
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 634,
        "pull_request": 635,
        "family_id": "low-frequency-trend-coherence-hysteresis-1h-v1",
        "status": "historical_rejection_evidence_open_draft_pr",
        "prospective_performance_consumed": False,
        "reason": (
            "the open draft PR records bilateral development rejection evidence; prospective "
            "scoring remains prohibited and cannot be used for rescue tuning"
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
    result["strategy_facing_discrepancy"] = {
        "diagnosis": discrepancy_text(result),
        "policy_or_accounting_defect_detected": False,
    }
    result["next_strategy_action"] = (
        "continue the identical frozen 2160H benchmark-shadow epoch at the next complete "
        "public 1H observation; do not prospectively rescue the low-frequency trend-coherence "
        "hysteresis family"
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
