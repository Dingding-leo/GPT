from __future__ import annotations

import argparse
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base

HOUR_MS = base.HOUR_MS
PREVIOUS_DECISION_HOUR_MS = 1_785_276_000_000  # 2026-07-28T22:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_279_600_000  # 2026-07-28T23:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_283_200_000  # 2026-07-29T00:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_286_800_000  # 2026-07-29T01:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_265_200_000  # 2026-07-28T19:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "8802385d7098e3fe1bdb55b30a233b8977e9c3f273261a90d840096c6c55bb83"
PRIOR_ARTIFACT_SHA256 = "559066eb3b10a4b3085396f7506ca6f98c90eb2ff6bd3b4a144acd8b48480c4f"


def configure_frozen_epoch() -> None:
    base.PREVIOUS_DECISION_HOUR_MS = PREVIOUS_DECISION_HOUR_MS
    base.REALIZED_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
    base.PRIOR_REPORTED_SIGNAL_HOUR_MS = PRIOR_REPORTED_SIGNAL_HOUR_MS
    base.LATEST_COMPLETE_SIGNAL_HOUR_MS = LATEST_COMPLETE_SIGNAL_HOUR_MS
    base.PRIOR_RESULT_SHA256 = PRIOR_RESULT_SHA256
    base.PRIOR_ARTIFACT_SHA256 = PRIOR_ARTIFACT_SHA256


def close_at(
    candles: dict[int, dict[str, Any]], timestamp_ms: int, instrument: str
) -> float:
    return float(base.require_candle(candles, timestamp_ms, instrument)["close"])


def drift_attribution(
    candles: dict[int, dict[str, Any]], instrument: str
) -> dict[str, Any]:
    prior_current = close_at(candles, PRIOR_REPORTED_SIGNAL_HOUR_MS, instrument)
    latest_current = close_at(candles, LATEST_COMPLETE_SIGNAL_HOUR_MS, instrument)
    prior_reference = close_at(
        candles,
        PRIOR_REPORTED_SIGNAL_HOUR_MS - base.LOOKBACK_HOURS * HOUR_MS,
        instrument,
    )
    latest_reference = close_at(
        candles,
        LATEST_COMPLETE_SIGNAL_HOUR_MS - base.LOOKBACK_HOURS * HOUR_MS,
        instrument,
    )
    current_return = latest_current / prior_current - 1.0
    reference_return = latest_reference / prior_reference - 1.0
    return {
        "prior_current_close": prior_current,
        "latest_current_close": latest_current,
        "current_close_return": current_return,
        "prior_lagged_reference_close": prior_reference,
        "latest_lagged_reference_close": latest_reference,
        "lagged_reference_return": reference_return,
        "interpretation": (
            "margin change is jointly determined by the completed-hour close and the "
            "rolling 2160H reference close; no policy parameter changed"
        ),
    }


def annualized_sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((value - mean) ** 2 for value in returns) / (len(returns) - 1)
    if variance <= 0.0:
        return None
    return mean / math.sqrt(variance) * math.sqrt(8_760.0)


def maximum_drawdown(returns: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    maximum = 0.0
    for value in returns:
        equity *= 1.0 + value
        peak = max(peak, equity)
        maximum = min(maximum, equity / peak - 1.0)
    return maximum


def compound_return(returns: list[float]) -> float:
    value = 1.0
    for item in returns:
        value *= 1.0 + item
    return value - 1.0


def recent_forward_window(
    candles: dict[int, dict[str, Any]], instrument: str
) -> dict[str, Any]:
    prior_hour = RECENT_WINDOW_FIRST_DECISION_HOUR_MS - HOUR_MS
    prior_target = int(base.signal_margin(candles, prior_hour, instrument) > 0.0)
    intervals: list[dict[str, Any]] = []
    strategy_returns: list[float] = []
    asset_returns: list[float] = []
    total_turnover = 0.0
    total_fees = 0.0
    long_decisions = 0

    for decision_hour in range(
        RECENT_WINDOW_FIRST_DECISION_HOUR_MS,
        RECENT_WINDOW_LAST_DECISION_HOUR_MS + HOUR_MS,
        HOUR_MS,
    ):
        margin = base.signal_margin(candles, decision_hour, instrument)
        target = int(margin > 0.0)
        turnover = abs(target - prior_target)
        fee = turnover * base.FEE_RATE
        payoff_start = decision_hour + HOUR_MS
        payoff_end = payoff_start + HOUR_MS
        start_open = float(base.require_candle(candles, payoff_start, instrument)["open"])
        end_open = float(base.require_candle(candles, payoff_end, instrument)["open"])
        asset_return = end_open / start_open - 1.0
        gross_return = target * asset_return
        net_return = gross_return - fee
        intervals.append(
            {
                "decision_hour_start": base.iso_utc(decision_hour),
                "position": target,
                "margin": margin,
                "payoff_open_start": base.iso_utc(payoff_start),
                "payoff_open_end": base.iso_utc(payoff_end),
                "asset_return": asset_return,
                "gross_strategy_return": gross_return,
                "net_strategy_return": net_return,
                "turnover": turnover,
                "modeled_fee": fee,
            }
        )
        strategy_returns.append(net_return)
        asset_returns.append(asset_return)
        total_turnover += turnover
        total_fees += fee
        long_decisions += target
        prior_target = target

    net_compound = compound_return(strategy_returns)
    benchmark_compound = compound_return(asset_returns)
    return {
        "first_decision_hour_start": base.iso_utc(RECENT_WINDOW_FIRST_DECISION_HOUR_MS),
        "last_decision_hour_start": base.iso_utc(RECENT_WINDOW_LAST_DECISION_HOUR_MS),
        "realized_interval_count": len(intervals),
        "intervals": intervals,
        "long_decision_count": long_decisions,
        "signal_frequency": long_decisions / len(intervals),
        "no_trade_frequency": 1.0 - long_decisions / len(intervals),
        "net_compound_return": net_compound,
        "benchmark_compound_return": benchmark_compound,
        "residual_vs_buy_and_hold": net_compound - benchmark_compound,
        "turnover": total_turnover,
        "modeled_fees": total_fees,
        "edge_per_turnover_bps": (
            net_compound / total_turnover * 10_000.0
            if total_turnover > 0.0
            else None
        ),
        "maximum_drawdown": maximum_drawdown(strategy_returns),
        "sharpe": annualized_sharpe(strategy_returns),
        "loss_count": sum(value < 0.0 for value in strategy_returns),
    }


def discrepancy_diagnosis(market: dict[str, Any]) -> dict[str, Any]:
    asset_return = float(market["realized_interval"]["asset_return"])
    margin_change = float(market["signal_drift"]["margin_change"])
    opposite = asset_return * margin_change < 0.0
    return {
        "type": (
            "benchmark_signal_direction_divergence"
            if opposite
            else "benchmark_signal_direction_alignment"
        ),
        "asset_return": asset_return,
        "signal_margin_change": margin_change,
        "intervals_are_distinct": True,
        "explanation": (
            "the realized benchmark is open-to-open, while signal drift compares "
            "completed-hour close-to-rolling-reference margins; opposite signs are not "
            "a timing defect"
            if opposite
            else "the open-to-open benchmark and completed-hour margin moved in the same "
            "direction, with no timing or fee discrepancy detected"
        ),
    }


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Prospective simple-trend shadow update through 01:00 UTC",
        "",
        f"- Policy SHA-256: `{result['policy_sha256']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- New complete signal bars: `{result['window']['new_signal_bar_count']}`",
        f"- Cumulative realized hours: `{result['window']['updated_cumulative_realized_hours']}`",
        "- Canonical fee: `5 bps one-way`",
        "",
        "| Market | Position | Net return | Asset return | Residual | Turnover | Fee | "
        "Latest margin | Margin drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realized = market["realized_interval"]
        drift = market["signal_drift"]
        lines.append(
            "| {instrument} | {position} | {net:.6%} | {asset:.6%} | "
            "{residual:.6%} | {turnover:.4f} | {fee:.6%} | {margin:.6%} | "
            "{margin_drift:+.6%} |".format(
                instrument=market["instrument"],
                position=realized["position"],
                net=realized["net_strategy_return"],
                asset=realized["asset_return"],
                residual=realized["strategy_residual_vs_buy_and_hold"],
                turnover=realized["turnover"],
                fee=realized["modeled_fee"],
                margin=drift["margin_at_latest_complete_signal_hour"],
                margin_drift=drift["margin_change"],
            )
        )
    lines.extend(
        [
            "",
            "## Five-interval recent forward window",
            "",
            "| Market | Long decisions | Net return | Benchmark | Residual | Turnover | "
            "Fees | Max drawdown | Sharpe |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market in result["markets"]:
        recent = market["recent_forward_window"]
        sharpe = "undefined" if recent["sharpe"] is None else f"{recent['sharpe']:.4f}"
        lines.append(
            "| {instrument} | {long}/{count} | {net:.6%} | {benchmark:.6%} | "
            "{residual:.6%} | {turnover:.4f} | {fees:.6%} | {drawdown:.6%} | "
            "{sharpe} |".format(
                instrument=market["instrument"],
                long=recent["long_decision_count"],
                count=recent["realized_interval_count"],
                net=recent["net_compound_return"],
                benchmark=recent["benchmark_compound_return"],
                residual=recent["residual_vs_buy_and_hold"],
                turnover=recent["turnover"],
                fees=recent["modeled_fees"],
                drawdown=recent["maximum_drawdown"],
                sharpe=sharpe,
            )
        )
    lines.extend(
        [
            "",
            f"Verdict: `{result['verdict']}`",
            "",
            "No policy correction was permitted or applied. No live or paper-trading "
            "authorization is implied.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    source_root = output_dir / "source"
    server_ms, server_source = base.fetch_server_time(base_url, source_root)
    minimum_server_ms = LATEST_COMPLETE_SIGNAL_HOUR_MS + HOUR_MS
    if server_ms < minimum_server_ms:
        raise ValueError(
            "frozen cutoff bar was not complete at acquisition: "
            f"server={base.iso_utc(server_ms)} required={base.iso_utc(minimum_server_ms)}"
        )

    market_results: list[dict[str, Any]] = []
    source_markets: list[dict[str, Any]] = []
    for instrument in base.MARKETS:
        candles, pages = base.fetch_candles(base_url, instrument, source_root / instrument)
        grid = base.validate_grid(candles, instrument)
        market = base.calculate_market(candles, instrument)
        market["drift_attribution"] = drift_attribution(candles, instrument)
        market["recent_forward_window"] = recent_forward_window(candles, instrument)
        market["discrepancy_diagnosis"] = discrepancy_diagnosis(market)
        realized = market["realized_interval"]
        realized["expected_net_return_under_frozen_decision"] = (
            0.0 if realized["position"] == 0 else None
        )
        market_results.append(market)
        source_markets.append(
            {
                "instrument": instrument,
                "pages": pages,
                "unique_candle_count": len(candles),
                "grid": grid,
            }
        )

    all_cash = all(
        market["realized_interval"]["position"] == 0
        and market["new_long_targets"] == 0
        for market in market_results
    )
    verdict = (
        "prospective_simple_trend_no_trade_continues"
        if all_cash
        else "prospective_simple_trend_exposure_observed_continue_shadow_only"
    )
    result = {
        "schema_version": 2,
        "generated_at": datetime.now(tz=UTC).isoformat().replace("+00:00", "Z"),
        "policy_name": "simple_trend_long_cash_2160h_next_open",
        "policy_signature": base.POLICY_SIGNATURE,
        "policy_sha256": base.sha256_bytes(base.POLICY_SIGNATURE.encode()),
        "architecture_status": "frozen_benchmark_shadow_only",
        "nomination_status": (
            "no_statistically_eligible_strategy_active_after_adaptive_state_rejection"
        ),
        "bar": base.BAR,
        "markets_independent": True,
        "cross_sectional_selection": False,
        "canonical_fee_bps_one_way": base.FEE_BPS_ONE_WAY,
        "actual_orders": False,
        "credentials_used": False,
        "private_endpoints_used": False,
        "enabled_adapters": False,
        "live_trading_authorized": False,
        "paper_trading_authorized": False,
        "reserved_trade_flow_oos_consumed": False,
        "adaptive_state_official_oos_consumed": False,
        "prospective_lineage": {
            "prior_result_sha256": PRIOR_RESULT_SHA256,
            "prior_artifact_sha256": PRIOR_ARTIFACT_SHA256,
            "prior_last_signal_bar_start": base.iso_utc(PRIOR_REPORTED_SIGNAL_HOUR_MS),
            "latest_complete_signal_bar_start": base.iso_utc(
                LATEST_COMPLETE_SIGNAL_HOUR_MS
            ),
            "policy_unchanged": True,
        },
        "window": {
            "prior_last_signal_bar_start_ms": PRIOR_REPORTED_SIGNAL_HOUR_MS,
            "prior_last_signal_bar_start": base.iso_utc(PRIOR_REPORTED_SIGNAL_HOUR_MS),
            "latest_complete_signal_bar_start_ms": LATEST_COMPLETE_SIGNAL_HOUR_MS,
            "latest_complete_signal_bar_start": base.iso_utc(
                LATEST_COMPLETE_SIGNAL_HOUR_MS
            ),
            "new_signal_bar_count": 1,
            "new_realized_payoff_intervals": 1,
            "prior_cumulative_realized_hours": 503,
            "updated_cumulative_realized_hours": 504,
        },
        "acquisition": server_source,
        "sources": source_markets,
        "markets": market_results,
        "abort_conditions": {
            "triggered": False,
            "conditions": [
                "server time before frozen cutoff completion",
                "missing or incomplete required 1H candle",
                "non-contiguous required 1H grid",
                "conflicting duplicate candle",
                "non-finite or non-positive required price",
                "public OKX response error or pagination non-advance",
            ],
        },
        "training_authorized_correction": {
            "permitted": False,
            "applied": False,
            "reason": (
                "the benchmark-shadow rule is immutable and no preregistered correction "
                "trigger exists; changing lookback, threshold, sizing, or timing would be "
                "rescue tuning"
            ),
        },
        "verdict": verdict,
        "next_strategy_action": (
            "continue the immutable benchmark-shadow epoch without policy changes while "
            "the research lane preregisters one orthogonal own-history-only 1H candidate; "
            "prospective evidence remains shadow-only"
        ),
    }
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
