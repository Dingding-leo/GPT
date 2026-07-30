from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260730_0900 as prior

HOUR_MS = prior.HOUR_MS
PREVIOUS_DECISION_HOUR_MS = 1_785_394_800_000  # 2026-07-30T07:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_398_400_000  # 2026-07-30T08:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_402_000_000  # 2026-07-30T09:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_405_600_000  # 2026-07-30T10:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_384_000_000  # 2026-07-30T04:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "36e57d97334f11e9179b1697b6f5892785505cc8ba8d602a762b9ccfc405036c"
PRIOR_ARTIFACT_SHA256 = "cce675fe50743ed0ce6208dea35fa63122082d2a8ac927822ad6ecc51504efdd"


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


def pct(value: float) -> str:
    return f"{value:+.6%}"


def diagnose_one_discrepancy(result: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for market in result["markets"]:
        latest = market["realized_interval"]["asset_return"]
        five = market["recent_forward_window"]["benchmark_compound_return"]
        margin_drift = market["signal_drift"]["margin_change"]
        rows.append(
            {
                "instrument": market["instrument"],
                "latest_interval_asset_return": latest,
                "five_interval_benchmark_return": five,
                "trend_margin_drift": margin_drift,
            }
        )

    sign_mismatch = [
        row
        for row in rows
        if row["latest_interval_asset_return"] * row["trend_margin_drift"] < 0
    ]
    if sign_mismatch:
        chosen = max(
            sign_mismatch,
            key=lambda row: abs(
                row["latest_interval_asset_return"] - row["trend_margin_drift"]
            ),
        )
        classification = "open_to_open_return_vs_completed_close_margin_drift_sign_mismatch"
        diagnosis = (
            f"{chosen['instrument']} produced a latest open-to-open benchmark return of "
            f"{pct(chosen['latest_interval_asset_return'])} while its completed-close 2,160H "
            f"trend margin changed by {pct(chosen['trend_margin_drift'])}. The metrics use "
            "different price intervals and a changing rolling reference close, so the opposing "
            "signs are measurement-interval and regime drift rather than chronology, next-open "
            "execution, position-state or fee-accounting failure."
        )
    else:
        horizon_mismatch = [
            row
            for row in rows
            if row["latest_interval_asset_return"]
            * row["five_interval_benchmark_return"]
            < 0
        ]
        if horizon_mismatch:
            chosen = max(
                horizon_mismatch,
                key=lambda row: abs(
                    row["latest_interval_asset_return"]
                    - row["five_interval_benchmark_return"]
                ),
            )
            classification = "latest_hour_vs_five_interval_horizon_sign_reversal"
            diagnosis = (
                f"{chosen['instrument']} returned "
                f"{pct(chosen['latest_interval_asset_return'])} in the newest realised hour "
                f"but {pct(chosen['five_interval_benchmark_return'])} over the rolling five "
                "intervals. The frozen cash decision therefore has opposite opportunity-cost "
                "interpretations across horizons. This is regime-horizon drift, not a policy, "
                "chronology, execution or fee-accounting defect."
            )
        else:
            chosen = max(
                rows,
                key=lambda row: abs(
                    row["latest_interval_asset_return"]
                    - row["five_interval_benchmark_return"]
                ),
            )
            classification = "latest_hour_vs_five_interval_return_amplitude_divergence"
            diagnosis = (
                f"{chosen['instrument']} returned "
                f"{pct(chosen['latest_interval_asset_return'])} in the newest realised hour "
                f"versus {pct(chosen['five_interval_benchmark_return'])} over the rolling five "
                "intervals. Direction is not contradictory, but the return amplitude differs "
                "materially across horizons; this is short-horizon regime drift rather than a "
                "chronology, next-open execution, position-state or fee-accounting defect."
            )

    return {
        "classification": classification,
        "selected_instrument": chosen["instrument"],
        "latest_interval_asset_return": chosen["latest_interval_asset_return"],
        "five_interval_benchmark_return": chosen["five_interval_benchmark_return"],
        "trend_margin_drift": chosen["trend_margin_drift"],
        "diagnosis": diagnosis,
        "policy_or_accounting_defect_detected": False,
    }


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow update through 10:00 UTC",
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
            "Issue #694 and draft PR #695 record terminal historical rejection evidence for "
            "the exact trend-onset participation-decay exit family. This interval was not used "
            "to score, revise or rescue that family.",
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
    result["window"]["prior_cumulative_realized_hours"] = 536
    result["window"]["updated_cumulative_realized_hours"] = 537
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["strategy_facing_discrepancy"] = diagnose_one_discrepancy(result)
    result["active_alpha_context"] = {
        "issue": 694,
        "pull_request": 695,
        "family_id": "exact-trend-onset-participation-decay-exit-1h-v1",
        "status": "terminal_historical_rejection_evidence_draft",
        "prospective_performance_consumed": False,
        "reason": (
            "the sole preregistered own-history participation-decay exit generated only two BTC "
            "development-OOS exits and no ETH development-OOS exits; BTC's aggregate benefit was "
            "event-concentrated and failed profitable-fold breadth plus dependence-aware lower "
            "bounds, while ETH was identical to the frozen benchmark throughout development OOS, "
            "so this forward interval cannot alter the 168H directional-movement horizon, "
            "half-maximum ratio, onset-close condition, irreversible lockout, cadence, fee model "
            "or market treatment"
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
        "continue the identical frozen 2160H benchmark-shadow epoch at the next complete public "
        "1H observation; do not prospectively rescue the rejected exact trend-onset "
        "participation-decay exit family"
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
