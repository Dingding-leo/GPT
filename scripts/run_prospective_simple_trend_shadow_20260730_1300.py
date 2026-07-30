from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260730_1200 as prior

HOUR_MS = prior.HOUR_MS
PREVIOUS_DECISION_HOUR_MS = 1_785_405_600_000  # 2026-07-30T10:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_409_200_000  # 2026-07-30T11:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_412_800_000  # 2026-07-30T12:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_416_400_000  # 2026-07-30T13:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_394_800_000  # 2026-07-30T07:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "123c5aa33f9c0dee016fc7877553d1b57375f66bf6f4d0c8d750ddd4ca4f9b7b"
PRIOR_ARTIFACT_SHA256 = "ea8c35820452c3409cc4c3d7bb8c68046e87fa24112c6feb6ae1231c375cdb71"


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
        "# Prospective simple-trend shadow update through 13:00 UTC",
        "",
        f"- Generated: `{result['generated_at']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- Policy: `{result['policy_name']}`",
        f"- Policy SHA-256: `{result['policy_sha256']}`",
        f"- Elapsed period: `{result['elapsed_period_hours']} hour`",
        f"- New complete public observations: `{result['new_public_observations_per_market']} per market`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        "- Canonical fee: `5 bps one-way`",
        "- Status: immutable benchmark-shadow evidence only; no paper/live authorisation",
        "",
        "| Market | Position | New target | Expected net | Realised net | Benchmark | Residual | Turnover | Fee | Latest margin | Margin drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realised = market["realized_interval"]
        drift = market["signal_drift"]
        lines.append(
            "| {instrument} | {position} | {target} | {expected:.6%} | {net:.6%} | "
            "{asset:+.6%} | {residual:+.6%} | {turnover:.4f} | {fee:.6%} | "
            "{margin:+.6%} | {margin_drift:+.6%} |".format(
                instrument=market["instrument"],
                position=realised["position"],
                target=market["new_decisions"][0]["target"],
                expected=realised["expected_net_return_under_frozen_decision"],
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
            "| Market | Long decisions | Net return | Benchmark | Residual | Turnover | Fees | Edge/turnover | Max drawdown | Sharpe | Losses |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market in result["markets"]:
        recent = market["recent_forward_window"]
        edge = recent["edge_per_turnover_bps"]
        lines.append(
            "| {instrument} | {long}/{count} | {net:.6%} | {benchmark:+.6%} | "
            "{residual:+.6%} | {turnover:.4f} | {fees:.6%} | {edge} | "
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
    correction = result["training_authorized_correction"]
    abort = result["abort_conditions"]
    lines.extend(
        [
            "",
            "## Strategy-facing discrepancy diagnosis",
            "",
            result["strategy_facing_discrepancy"]["diagnosis"],
            "",
            "## Correction protocol",
            "",
            f"- Correction permitted: `{correction['permitted']}`",
            f"- Correction applied: `{correction['applied']}`",
            "- Policy changed: `false`",
            "- Observation epoch restarted: `false`",
            "",
            "Issue #705 and closed unmerged PR #706 contain terminal historical rejection evidence for the exact sign-transition entropy persistence overlay. BTC risk-state transitions removed profitable continuation; ETH's short-horizon information was overwhelmed by persistent half exposure and added turnover. Both markets failed the preregistered breadth, efficiency, residual-Sharpe, and dependence-aware uncertainty gates. This forward interval was not consumed to revise or rescue that family.",
            "",
            "## Abort conditions and verdict",
            "",
            f"- Abort triggered: `{abort['triggered']}`",
            f"- Verdict: `{result['verdict']}`",
            f"- Next action: {result['next_strategy_action']}",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 539
    result["window"]["updated_cumulative_realized_hours"] = 540
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 705,
        "pull_request": 706,
        "family_id": "sign-transition-entropy-persistence-overlay-1h-v1",
        "status": "terminal_historical_rejection_evidence_closed_unmerged",
        "prospective_performance_consumed": False,
        "reason": (
            "BTC's 27 effective risk transitions were followed by positive 168H continuation, "
            "while ETH's partially informative state remained active too long and added fees. "
            "Both markets failed required fold/year breadth, turnover efficiency, residual "
            "Sharpe, and strict dependence-aware lower-bound gates; no rescue is authorised."
        ),
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": (
            "the new interval contains frozen long exposure and contributes conditional-long forward evidence"
            if exposed
            else "the new interval is cash-only, so it supplies no realised conditional-long return and cannot validate historical selection persistence"
        ),
    }
    result["next_strategy_action"] = (
        "continue the identical frozen 2160H benchmark-shadow epoch at the next complete public "
        "1H observation; do not prospectively rescue the rejected sign-transition entropy "
        "persistence overlay family"
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
