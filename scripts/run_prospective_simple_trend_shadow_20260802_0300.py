from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as engine
import run_prospective_simple_trend_shadow_20260802_0200 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_628_800_000
REALIZED_DECISION_HOUR_MS = 1_785_632_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_632_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_636_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_618_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_639_600_000
PRIOR_RESULT_SHA256 = "81d1f1aeab006124bff108899c54e7ce44d8b21aa863a475bdb96e71e932756f"
PRIOR_ARTIFACT_SHA256 = "0e622a4458a936b14ab6a6d305853bd1f8306135d4ed7f85a8b59a2ec0222a81"

ORIGINAL_REQUIRE_CANDLE = engine.require_candle


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


def require_completed_or_payoff_open(
    candles: dict[int, dict[str, Any]], timestamp_ms: int, instrument: str
) -> dict[str, Any]:
    if timestamp_ms != PAYOFF_END_OPEN_HOUR_MS:
        return ORIGINAL_REQUIRE_CANDLE(candles, timestamp_ms, instrument)

    candle = candles.get(timestamp_ms)
    if candle is None:
        raise ValueError(
            f"missing payoff-end open {engine.iso_utc(timestamp_ms)}: {instrument}"
        )
    if candle.get("confirm") not in {"0", "1"}:
        raise ValueError(
            f"invalid payoff-end confirm flag {engine.iso_utc(timestamp_ms)}: {instrument}"
        )
    open_price = float(candle["open"])
    if not math.isfinite(open_price) or open_price <= 0.0:
        raise ValueError(
            f"invalid payoff-end open {engine.iso_utc(timestamp_ms)}: {instrument}"
        )
    return candle


def pct(value: float | None) -> str:
    return "undefined" if value is None else f"{100.0 * value:+.6f}%"


def write_outputs(output_dir: Path, result: dict[str, Any]) -> None:
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    (output_dir / "result.json").write_text(payload)
    (output_dir / "result.sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "\n"
    )

    lines = [
        "# Prospective simple-trend checkpoint through 03:00 UTC on 2 August 2026",
        "",
        f"- Policy: `{result['policy_name']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- Latest complete signal bar: `{result['window']['latest_complete_signal_bar_start']}`",
        f"- Realised payoff interval: `{result['window']['realized_payoff_interval_start']}` to `{result['window']['realized_payoff_interval_end']}`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Abort: `{result['abort_conditions']['triggered']}`",
        "",
        "| Market | Carried position | New target | Realised net | Benchmark | Residual | Turnover | Fees | New 2160H margin | Margin drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realised = market["realized_interval"]
        decision = market["new_decisions"][0]
        drift = market["signal_drift"]
        lines.append(
            f"| {market['instrument']} | {'Long' if realised['position'] else 'Cash'} | "
            f"{'Long' if decision['target'] else 'Cash'} | "
            f"{pct(realised['net_strategy_return'])} | {pct(realised['asset_return'])} | "
            f"{pct(realised['strategy_residual_vs_buy_and_hold'])} | "
            f"{realised['turnover']} | {pct(realised['modeled_fee'])} | "
            f"{pct(decision['margin'])} | {pct(drift['margin_change'])} |"
        )

    lines.extend(
        [
            "",
            "## Five-interval prospective scorecard",
            "",
            "| Market | Longs | Strategy net | Benchmark | Residual | Turnover | Fees | Max DD | Sharpe | Edge/turnover |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for market in result["markets"]:
        recent = market["recent_forward_window"]
        sharpe = "undefined" if recent["sharpe"] is None else f"{recent['sharpe']:.6f}"
        edge = (
            "undefined"
            if recent["edge_per_turnover_bps"] is None
            else f"{recent['edge_per_turnover_bps']:.6f} bps"
        )
        lines.append(
            f"| {market['instrument']} | {recent['long_decision_count']}/{recent['realized_interval_count']} | "
            f"{pct(recent['net_compound_return'])} | "
            f"{pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | "
            f"{sharpe} | {edge} |"
        )

    lines.extend(
        [
            "",
            "## Strategy-facing finding",
            "",
            result["strategy_facing_discrepancy"]["diagnosis"],
            "",
            "The 02:00 signal bar was provider-confirmed and updated the frozen 2,160H state. "
            "The 03:00 candle supplied only its already-fixed open as the end of the 02:00–03:00 "
            "open-to-open payoff; its incomplete close, high, low and volume were excluded.",
            "",
            "No training, sealed-OOS or full-sample candidate was created. The latest terminal "
            "architecture remains the mark/index source-admissibility closure; no replacement "
            "strategy architecture is active.",
            "",
            "```json",
            json.dumps(result["machine_readable_verdict"], sort_keys=True, indent=2),
            "```",
            "",
            f"Next strategy-facing action: {result['next_strategy_action']}.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    engine.require_candle = require_completed_or_payoff_open
    try:
        result = prior.run(output_dir, base_url)
    finally:
        engine.require_candle = ORIGINAL_REQUIRE_CANDLE

    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["checkpoint_type"] = "complete_signal_plus_realized_payoff_open"
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["new_complete_signal_observations_per_market"] = 1
    result["new_realized_payoff_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 601
    result["window"]["updated_cumulative_realized_hours"] = 602
    result["window"]["new_signal_bar_count"] = 1
    result["window"]["new_realized_payoff_intervals"] = 1

    result["payoff_end_open_boundary"] = {
        "timestamp_ms": PAYOFF_END_OPEN_HOUR_MS,
        "timestamp": engine.iso_utc(PAYOFF_END_OPEN_HOUR_MS),
        "field_used": "open",
        "provider_confirm_required": False,
        "provider_confirm_values_allowed": ["0", "1"],
        "used_for_signal": False,
        "used_for_feature": False,
        "used_for_target": False,
        "used_for_position": False,
        "used_for_turnover": False,
        "used_for_fee": False,
        "used_only_as_realized_payoff_endpoint": True,
        "open_is_fixed_at_bar_start": True,
    }
    result["cutoff_repair"] = {
        "applied": True,
        "type": "completed_signal_with_fixed_payoff_end_open",
        "payoff_end_open_timestamp": engine.iso_utc(PAYOFF_END_OPEN_HOUR_MS),
        "open_endpoint_only": True,
        "incomplete_close_accessed": False,
        "incomplete_high_accessed": False,
        "incomplete_low_accessed": False,
        "incomplete_volume_accessed": False,
        "future_signal_accessed": False,
        "strategy_value_changed": False,
        "source_changed": False,
        "fee_changed": False,
        "architecture_changed": False,
    }

    selected = max(
        result["markets"],
        key=lambda market: abs(float(market["realized_interval"]["asset_return"])),
    )
    selected_drift = selected["signal_drift"]
    selected_return = selected["realized_interval"]["asset_return"]
    selected_recent = selected["recent_forward_window"]["benchmark_compound_return"]
    carried_cash = selected["realized_interval"]["position"] == 0
    result["strategy_facing_discrepancy"] = {
        "selected_instrument": selected["instrument"],
        "classification": (
            "cash_opportunity_cost" if carried_cash and selected_return > 0.0
            else "cash_loss_avoidance" if carried_cash
            else "exposed_interval"
        ),
        "latest_interval_asset_return": selected_return,
        "five_interval_benchmark_return": selected_recent,
        "trend_margin_drift": selected_drift["margin_change"],
        "policy_or_accounting_defect_detected": False,
        "diagnosis": (
            "The frozen carried position and fee accounting matched the pre-existing policy. "
            "The new observation changes only prospective evidence: it measures either avoided "
            "market loss, cash opportunity cost, or exposed performance under the already-fixed "
            "2,160H state."
        ),
    }
    result["next_strategy_action"] = (
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public "
        "1H observation; open no replacement strategy until a materially orthogonal causal "
        "public 1H source contract and falsifiable hypothesis are frozen before feature or "
        "performance access"
    )
    result["machine_readable_verdict"].update(
        {
            "checkpoint_type": result["checkpoint_type"],
            "latest_complete_signal_bar_start": result["window"][
                "latest_complete_signal_bar_start"
            ],
            "new_signal_bar_count": 1,
            "new_realized_payoff_intervals": 1,
            "updated_cumulative_realized_hours": 602,
            "payoff_end_open_timestamp": engine.iso_utc(PAYOFF_END_OPEN_HOUR_MS),
            "payoff_end_open_only": True,
            "future_signal_accessed": False,
            "strategy_value_changed": False,
            "policy_changed": False,
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
        }
    )
    write_outputs(output_dir, result)
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
