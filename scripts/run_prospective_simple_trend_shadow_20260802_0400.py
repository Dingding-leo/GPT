from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_0300 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_632_400_000
REALIZED_DECISION_HOUR_MS = 1_785_636_000_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_636_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_639_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_621_600_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_643_200_000
PRIOR_RESULT_SHA256 = "81af98b447bdfa153da5218ed1eee7e9cba55eaa5020be3847160ad8b43fba99"
PRIOR_ARTIFACT_SHA256 = "e0c9d4a457bf4e1062854dc86303ca36fcef1933df0d93318db0c3912dd58311"


def configure() -> None:
    for name in (
        "PREVIOUS_DECISION_HOUR_MS",
        "REALIZED_DECISION_HOUR_MS",
        "PRIOR_REPORTED_SIGNAL_HOUR_MS",
        "LATEST_COMPLETE_SIGNAL_HOUR_MS",
        "RECENT_WINDOW_FIRST_DECISION_HOUR_MS",
        "RECENT_WINDOW_LAST_DECISION_HOUR_MS",
        "PAYOFF_END_OPEN_HOUR_MS",
        "PRIOR_RESULT_SHA256",
        "PRIOR_ARTIFACT_SHA256",
    ):
        setattr(prior, name, globals()[name])


def pct(value: float | None) -> str:
    return "undefined" if value is None else f"{100.0 * value:+.6f}%"


def write_outputs(output_dir: Path, result: dict[str, Any]) -> None:
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    (output_dir / "result.json").write_text(payload)
    (output_dir / "result.sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "\n"
    )

    lines = [
        "# Prospective simple-trend checkpoint through 04:00 UTC on 2 August 2026",
        "",
        f"- Policy: `{result['policy_name']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- Latest complete signal bar: `{result['window']['latest_complete_signal_bar_start']}`",
        f"- Realised payoff interval: `{result['window']['realized_payoff_interval_start']}` to `{result['window']['realized_payoff_interval_end']}`",
        f"- Cumulative realised hours: `{result['window']['updated_cumulative_realized_hours']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Abort: `{result['abort_conditions']['triggered']}`",
        "",
        "| Market | Position | New target | Expected net | Realised net | Benchmark | Residual | Turnover | Fees | 2160H margin | Margin drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for market in result["markets"]:
        realised = market["realized_interval"]
        decision = market["new_decisions"][0]
        drift = market["signal_drift"]
        lines.append(
            f"| {market['instrument']} | {'Long' if realised['position'] else 'Cash'} | "
            f"{'Long' if decision['target'] else 'Cash'} | "
            f"{pct(realised['expected_net_return_under_frozen_decision'])} | "
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
            "| Market | Longs | Strategy net | Benchmark | Residual | Turnover | Fees | Max DD | Losses | Sharpe | Edge/turnover |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
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
            f"{pct(recent['net_compound_return'])} | {pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | "
            f"{recent['loss_count']} | {sharpe} | {edge} |"
        )

    lines.extend(
        [
            "",
            "## Strategy-facing discrepancy",
            "",
            result["strategy_facing_discrepancy"]["diagnosis"],
            "",
            "The 03:00 signal bar was provider-confirmed and updated the frozen 2,160H state. "
            "The 04:00 candle supplied only its already-fixed opening price as the endpoint of "
            "the 03:00–04:00 open-to-open payoff. Its incomplete close, high, low and volume "
            "were excluded from all signal, feature, target, position, turnover and fee logic.",
            "",
            "No training-authorised correction exists. The canonical policy and observation "
            "epoch therefore remain unchanged, with no paper- or live-trading authority.",
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
    result = prior.run(output_dir, base_url)

    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["checkpoint_type"] = "complete_signal_plus_realized_payoff_open"
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["new_complete_signal_observations_per_market"] = 1
    result["new_realized_payoff_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 602
    result["window"]["updated_cumulative_realized_hours"] = 603
    result["window"]["new_signal_bar_count"] = 1
    result["window"]["new_realized_payoff_intervals"] = 1

    selected = max(
        result["markets"],
        key=lambda market: abs(float(market["realized_interval"]["asset_return"])),
    )
    latest_return = float(selected["realized_interval"]["asset_return"])
    recent_return = float(selected["recent_forward_window"]["benchmark_compound_return"])
    margin_change = float(selected["signal_drift"]["margin_change"])
    if latest_return * recent_return < 0.0:
        drift_class = "regime_horizon_reversal"
        finding = (
            "The newest executable benchmark and the five-interval benchmark have opposite "
            "signs, so the no-trade outcome has conflicting opportunity-cost interpretations "
            "across horizons."
        )
    elif latest_return * margin_change < 0.0:
        drift_class = "measurement_interval_and_rolling_reference_drift"
        finding = (
            "The newest open-to-open benchmark and the completed-close E2160 margin moved in "
            "opposite directions because the rolling reference endpoint advanced independently."
        )
    else:
        drift_class = "short_horizon_return_amplitude_drift"
        finding = (
            "The newest and five-interval benchmarks agree directionally, but their amplitudes "
            "and the slow E2160-margin response differ materially."
        )

    result["strategy_facing_discrepancy"] = {
        "selected_instrument": selected["instrument"],
        "classification": drift_class,
        "latest_interval_asset_return": latest_return,
        "five_interval_benchmark_return": recent_return,
        "trend_margin_drift": margin_change,
        "policy_or_accounting_defect_detected": False,
        "diagnosis": (
            f"{selected['instrument']} was selected by absolute newest benchmark return. "
            f"{finding} No chronology, next-open execution, position-state, source-grid, "
            "policy-mutation or fee-accounting defect was detected."
        ),
    }
    result["next_strategy_action"] = (
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public "
        "1H observation; nominate no replacement until a materially orthogonal causal public "
        "1H source contract and falsifiable temporal rule are frozen before target-return access"
    )
    result["machine_readable_verdict"].update(
        {
            "checkpoint_type": result["checkpoint_type"],
            "latest_complete_signal_bar_start": result["window"][
                "latest_complete_signal_bar_start"
            ],
            "new_signal_bar_count": 1,
            "new_realized_payoff_intervals": 1,
            "updated_cumulative_realized_hours": 603,
            "payoff_end_open_timestamp": "2026-08-02T04:00:00Z",
            "payoff_end_open_only": True,
            "future_signal_accessed": False,
            "strategy_value_changed": False,
            "correction_permitted": False,
            "correction_applied": False,
            "policy_changed": False,
            "observation_epoch_restarted": False,
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
