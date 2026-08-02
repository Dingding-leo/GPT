from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_1100 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_661_200_000
REALIZED_DECISION_HOUR_MS = 1_785_664_800_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_664_800_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_668_400_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_650_400_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_672_000_000

PRIOR_RESULT_SHA256 = "9e8531ea1e5e5ddcc6fd0e4a62afed6422bf4b2dd5347a15833f8d53f5874a6b"
PRIOR_ARTIFACT_SHA256 = "caeb4765971ed7f8280e619c466e2727ac249dfd9ffdcd66fab31b2b2262cddf"
PRIOR_PULL_REQUEST = 969
PRIOR_WORKFLOW_RUN = 30745580004
PRIOR_ARTIFACT_ID = 8832759091
PRIOR_CUMULATIVE_REALIZED_HOURS = 610
UPDATED_CUMULATIVE_REALIZED_HOURS = 611


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
            "| {instrument} | {position} | {target} | {realized} | {benchmark} | "
            "{residual} | {turnover} | {fee} | {margin} | {drift} |".format(
                instrument=market["instrument"],
                position="Long" if interval["position"] else "Cash",
                target="Long" if decision["target"] else "Cash",
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
    report = f"""# Prospective simple-trend checkpoint through 12:00 UTC on 2 August 2026

- Policy: `{result["policy_name"]}`
- Acquisition server time: `{result["acquisition"]["server_time"]}`
- Latest complete signal bar: `{window["latest_complete_signal_bar_start"]}`
- Realised payoff interval: `{window["realized_payoff_interval_start"]}` to `{window["realized_payoff_interval_end"]}`
- Cumulative realised hours: `{window["updated_cumulative_realized_hours"]}`
- Fee: exactly `{result["canonical_fee_bps_one_way"]}` bps one way
- Abort: `{result["abort_conditions"]["triggered"]}`

| Market | Carried position | New target | Realised net | Benchmark | Residual | Turnover | Fees | New 2160H margin | Margin drift |
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

The 11:00 signal bar was provider-confirmed and updated the frozen 2,160H state.
The 12:00 candle supplied only its already-fixed open as the end of the
11:00–12:00 open-to-open payoff. Its incomplete close, high, low and volume
were excluded from every signal, feature, target, position, turnover and fee
calculation.

The terminal training-only directional-diffusion diagnostic in issue #963 /
PR #964 remains rejected with candidate count zero. No active replacement
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
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "no completed architecture has bilateral promotion authority; the "
            "fixed-universe directional-diffusion information premise was rejected "
            "with candidate count zero, and no active replacement architecture exists"
        ),
    }
    result["next_strategy_action"] = (
        "advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation; do not reopen the rejected "
        "directional-diffusion premise, and freeze any materially orthogonal causal "
        "source contract and falsifiable temporal rule before feature or target-return access"
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
    machine["terminal_training_diagnostic_verdict"] = result[
        "terminal_training_diagnostic"
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
