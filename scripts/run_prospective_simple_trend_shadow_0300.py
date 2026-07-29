from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_0200 as prior

HOUR_MS = prior.HOUR_MS
PREVIOUS_DECISION_HOUR_MS = 1_785_283_200_000  # 2026-07-29T00:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_286_800_000  # 2026-07-29T01:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_290_400_000  # 2026-07-29T02:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_294_000_000  # 2026-07-29T03:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_272_400_000  # 2026-07-28T21:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "b584505119effbb234242f0256ffa30a5c51efd15b0a99380cfe1ce1ea76e843"
PRIOR_ARTIFACT_SHA256 = "b7d6a9650a49aa5c38ceb1c400fa2e4e4d14c971ebd9e67877fe67ecf0f9c5bf"


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
        "# Prospective simple-trend shadow update through 03:00 UTC",
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
            "## Strategy-facing diagnosis",
            "",
            "The frozen 2160H policy was not altered. Any divergence between the "
            "open-to-open asset payoff and completed-close signal-margin drift is "
            "attributed explicitly in the machine-readable market records rather than "
            "treated as a timing or fee defect.",
            "",
            "Issue #595's variance-ratio architecture is terminally rejected on its "
            "historical development evidence and remains prospectively unscored. The "
            "current forward update therefore evaluates only the immutable benchmark-shadow "
            "policy and cannot rescue or promote the rejected family.",
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
    result["window"]["prior_cumulative_realized_hours"] = 505
    result["window"]["updated_cumulative_realized_hours"] = 506
    result["nomination_status"] = (
        "no_statistically_eligible_strategy_after_variance_ratio_rejection"
    )
    result["active_alpha_context"] = {
        "issue": 595,
        "family_id": "variance-ratio-persistence-state-1h-v1",
        "status": "terminally_rejected_historical_development",
        "prospective_performance_consumed": False,
        "reason": (
            "the preregistered development comparison rejected the family; prospective "
            "scoring remains prohibited and cannot be used for rescue tuning"
        ),
    }
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": any(
            market["realized_interval"]["position"] == 1 for market in result["markets"]
        ),
        "reason": (
            "a cash-only new interval supplies no realized conditional-long return and "
            "therefore cannot validate historical selection persistence"
        ),
    }
    result["next_strategy_action"] = (
        "continue the immutable 2160H benchmark-shadow epoch at the next complete 1H "
        "observation; separately preregister one own-history-only causal duration/hazard "
        "architecture before inspecting development performance"
    )
    prior.prior.base.write_outputs(output_dir, result)
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
