from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_1200 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_664_800_000
REALIZED_DECISION_HOUR_MS = 1_785_668_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_668_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_672_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_654_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_675_600_000

PRIOR_RESULT_SHA256 = "3126159d8289157d5973ae9dfb5d6976fe42e530f64ef1ba829c480b328e1b2b"
PRIOR_ARTIFACT_SHA256 = "ba534ad5e6954dd9ddaf08708e8cbf77719aebeed8ec60c20a2cb484427c4133"
PRIOR_PULL_REQUEST = 972
PRIOR_WORKFLOW_RUN = 30747493687
PRIOR_ARTIFACT_ID = 8833338691
PRIOR_CUMULATIVE_REALIZED_HOURS = 611
UPDATED_CUMULATIVE_REALIZED_HOURS = 612


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


def iso_utc(hour_ms: int) -> str:
    return (
        datetime.fromtimestamp(hour_ms / 1000.0, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def pct(value: float) -> str:
    return f"{value:+.6%}"


def scalar(value: Any) -> str:
    if value is None:
        return "undefined"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def write_result(output_dir: Path, result: dict[str, Any]) -> None:
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    (output_dir / "result.json").write_text(payload)
    (output_dir / "result.sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "\n"
    )


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    window = result["window"]
    rows: list[str] = []
    score_rows: list[str] = []
    for market in result["markets"]:
        interval = market["realized_interval"]
        decision = market["new_decisions"][0]
        recent = market["recent_forward_window"]
        rows.append(
            "| {instrument} | {position} | {target} | {expected} / {realized} | "
            "{benchmark} | {residual} | {turnover} | {fee} | {margin} | {drift} |".format(
                instrument=market["instrument"],
                position="Long" if interval["position"] else "Cash",
                target="Long" if decision["target"] else "Cash",
                expected=pct(interval["expected_net_return_under_frozen_decision"]),
                realized=pct(interval["net_strategy_return"]),
                benchmark=pct(interval["asset_return"]),
                residual=pct(interval["strategy_residual_vs_buy_and_hold"]),
                turnover=scalar(interval["turnover"]),
                fee=pct(interval["modeled_fee"]),
                margin=pct(decision["margin"]),
                drift=pct(market["signal_drift"]["margin_change"]),
            )
        )
        score_rows.append(
            "| {instrument} | {longs}/{count} | {net} | {benchmark} | {residual} | "
            "{turnover} | {fees} | {max_dd} | {losses} | {sharpe} | {edge} |".format(
                instrument=market["instrument"],
                longs=recent["long_decision_count"],
                count=recent["realized_interval_count"],
                net=pct(recent["net_compound_return"]),
                benchmark=pct(recent["benchmark_compound_return"]),
                residual=pct(recent["residual_vs_buy_and_hold"]),
                turnover=scalar(recent["turnover"]),
                fees=pct(recent["modeled_fees"]),
                max_dd=pct(recent["maximum_drawdown"]),
                losses=recent["loss_count"],
                sharpe=scalar(recent["sharpe"]),
                edge=(
                    "undefined"
                    if recent["edge_per_turnover_bps"] is None
                    else f'{recent["edge_per_turnover_bps"]:.6f} bps'
                ),
            )
        )

    discrepancy = result["strategy_facing_discrepancy"]
    verdict = result["machine_readable_verdict"]
    report = f"""# Prospective simple-trend checkpoint through 13:00 UTC on 2 August 2026

- Policy: `{result["policy_name"]}`
- Acquisition server time: `{result["acquisition"]["server_time"]}`
- Latest complete signal bar: `{window["latest_complete_signal_bar_start"]}`
- Realised payoff interval: `{window["realized_payoff_interval_start"]}` to `{window["realized_payoff_interval_end"]}`
- Cumulative realised hours: `{window["updated_cumulative_realized_hours"]}`
- Fee: exactly `{result["canonical_fee_bps_one_way"]}` bps one way
- Abort: `{result["abort_conditions"]["triggered"]}`

| Market | Carried position | New target | Expected / realised net | Benchmark | Residual | Turnover | Fees | New 2160H margin | Margin drift |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

## Five-interval prospective scorecard

| Market | Longs | Strategy net | Benchmark | Residual | Turnover | Fees | Max DD | Losses | Sharpe | Edge/turnover |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(score_rows)}

## Strategy-facing finding

Selected discrepancy: `{discrepancy["selected_instrument"]}` / `{discrepancy["classification"]}`.

Latest benchmark return: `{pct(discrepancy["latest_interval_asset_return"])}`.
Five-interval benchmark return: `{pct(discrepancy["five_interval_benchmark_return"])}`.
E2160 margin drift: `{pct(discrepancy["trend_margin_drift"])}`.

{discrepancy["diagnosis"]}

The 12:00 signal bar was provider-confirmed and updated the frozen 2,160H state.
The 13:00 candle supplied only its already-fixed open as the end of the
12:00–13:00 open-to-open payoff. Its incomplete close, high, low and volume
were excluded from every signal, feature, target, position, turnover and fee
calculation.

The latest additional training-only hour-of-week seasonal-projection
architecture in PR #973 was rejected with targets passing 0/2, candidate count
zero, parameter grid zero and no executable authority. No active replacement
strategy architecture, training-authorised correction or replacement
observation epoch exists.

```json
{json.dumps(verdict, sort_keys=True, indent=2, allow_nan=False)}
```

Next strategy-facing action: {result["next_strategy_action"]}.
"""
    (output_dir / "report.md").write_text(report)


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["window"]["prior_cumulative_realized_hours"] = (
        PRIOR_CUMULATIVE_REALIZED_HOURS
    )
    result["window"]["updated_cumulative_realized_hours"] = (
        UPDATED_CUMULATIVE_REALIZED_HOURS
    )
    result["performance_accessed"] = False
    result["oos_accessed"] = False
    result["prospective_lineage"]["prior_result_sha256"] = PRIOR_RESULT_SHA256
    result["prospective_lineage"]["prior_artifact_sha256"] = PRIOR_ARTIFACT_SHA256
    result["checkpoint_replication"] = {
        "type": "new_hour_after_exact_prior_checkpoint",
        "prior_pull_request": PRIOR_PULL_REQUEST,
        "prior_workflow_run": PRIOR_WORKFLOW_RUN,
        "prior_artifact_id": PRIOR_ARTIFACT_ID,
        "prior_result_sha256": PRIOR_RESULT_SHA256,
        "prior_artifact_sha256": PRIOR_ARTIFACT_SHA256,
        "policy_unchanged": True,
        "source_contract_unchanged": True,
        "fee_unchanged": True,
    }
    result["active_alpha_context"] = {
        "issue": None,
        "pull_request": None,
        "family_id": None,
        "classification": "no_active_replacement_strategy_architecture",
        "status": "none",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "performance_seen": False,
        "oos_accessed": False,
        "new_market_data": 0,
        "new_target_returns": 0,
        "new_oos_consumed": 0,
        "correction_permitted": False,
        "canonical_mutation_permitted": False,
    }
    result["latest_training_only_architecture"] = {
        "family_id": "causal-own-price-hour-of-week-seasonal-projection-opportunity-1h-v1",
        "pull_request": 973,
        "exact_tested_head": "0d2c2ade22a0899082a31f5966f8757e9ae15230",
        "workflow_run": 30748195126,
        "artifact_id": 8833592289,
        "targets_passing": 0,
        "target_count": 2,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "sealed_oos_accessed": False,
        "verdict": (
            "reject_causal_own_price_hour_of_week_seasonal_projection_"
            "information_premise_1h_v1"
        ),
        "correction_authority": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "no completed architecture has bilateral promotion authority; the latest "
            "own-price hour-of-week seasonal-projection information premise was "
            "rejected with targets passing zero of two and candidate count zero, and "
            "no active replacement architecture exists"
        ),
    }
    result["next_strategy_action"] = (
        "advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation; do not rescue the rejected "
        "hour-of-week seasonal-projection family, and freeze any materially "
        "orthogonal causal source contract and falsifiable temporal rule before "
        "feature or target-return access"
    )

    machine = result["machine_readable_verdict"]
    machine["updated_cumulative_realized_hours"] = UPDATED_CUMULATIVE_REALIZED_HOURS
    machine["payoff_end_open_timestamp"] = iso_utc(PAYOFF_END_OPEN_HOUR_MS)
    machine["correction_permitted"] = False
    machine["correction_applied"] = False
    machine["policy_changed"] = False
    machine["observation_epoch_restarted"] = False
    machine["active_family_id"] = None
    machine["active_family_status"] = "no_active_replacement_strategy_architecture"
    machine["latest_training_diagnostic_verdict"] = result[
        "latest_training_only_architecture"
    ]["verdict"]

    write_result(output_dir, result)
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
