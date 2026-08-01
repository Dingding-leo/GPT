from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_2300 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_531_600_000  # 2026-07-31T21:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_535_200_000  # 2026-07-31T22:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_538_800_000  # 2026-07-31T23:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_542_400_000  # 2026-08-01T00:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_520_800_000  # 2026-07-31T18:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "41c0484c42c59544d1317cd5a11739bae77489433679a118845eb92b3a18bcd3"
PRIOR_ARTIFACT_SHA256 = "7a97dd6b2c8d0005f63b7bd19891b23988d25715d4a492145475e8c15ab6c70e"


def configure_frozen_epoch() -> None:
    prior.PREVIOUS_DECISION_HOUR_MS = PREVIOUS_DECISION_HOUR_MS
    prior.REALIZED_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
    prior.PRIOR_REPORTED_SIGNAL_HOUR_MS = PRIOR_REPORTED_SIGNAL_HOUR_MS
    prior.LATEST_COMPLETE_SIGNAL_HOUR_MS = LATEST_COMPLETE_SIGNAL_HOUR_MS
    prior.RECENT_WINDOW_FIRST_DECISION_HOUR_MS = RECENT_WINDOW_FIRST_DECISION_HOUR_MS
    prior.RECENT_WINDOW_LAST_DECISION_HOUR_MS = RECENT_WINDOW_LAST_DECISION_HOUR_MS
    prior.PRIOR_RESULT_SHA256 = PRIOR_RESULT_SHA256
    prior.PRIOR_ARTIFACT_SHA256 = PRIOR_ARTIFACT_SHA256


def pct(value: float | None) -> str:
    return "undefined" if value is None else f"{100.0 * value:+.6f}%"


def number(value: float | None, digits: int = 6) -> str:
    return "undefined" if value is None else f"{value:.{digits}f}"


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    rows = []
    recent_rows = []
    for market in result["markets"]:
        realized = market["realized_interval"]
        rows.append(
            "| {instrument} | {position} | {target} | {net} | {benchmark} | {residual} | "
            "{turnover} | {fees} | {margin} | {drift} |".format(
                instrument=market["instrument"],
                position="Long" if realized["position"] else "Cash",
                target="Long" if market["new_decisions"][0]["target"] else "Cash",
                net=pct(realized["net_strategy_return"]),
                benchmark=pct(realized["asset_return"]),
                residual=pct(realized["strategy_residual_vs_buy_and_hold"]),
                turnover=realized["turnover"],
                fees=pct(realized["modeled_fee"]),
                margin=pct(market["new_decisions"][0]["margin"]),
                drift=pct(market["discrepancy_diagnosis"]["signal_margin_change"]),
            )
        )
        recent = market["recent_forward_window"]
        recent_rows.append(
            "| {instrument} | {longs}/{count} | {net} | {benchmark} | {residual} | "
            "{turnover} | {fees} | {dd} | {sharpe} | {edge} |".format(
                instrument=market["instrument"],
                longs=sum(int(x["position"]) for x in recent["intervals"]),
                count=recent["realized_interval_count"],
                net=pct(recent["net_compound_return"]),
                benchmark=pct(recent["benchmark_compound_return"]),
                residual=pct(recent["residual_vs_buy_and_hold"]),
                turnover=recent["turnover"],
                fees=pct(recent["modeled_fees"]),
                dd=pct(recent["maximum_drawdown"]),
                sharpe=number(recent["sharpe"]),
                edge=number(recent["edge_per_turnover_bps"]),
            )
        )

    discrepancy = result["strategy_facing_discrepancy"]
    active = result["active_alpha_context"]
    verdict = {
        "latest_complete_signal_bar_start": result["window"]["latest_complete_signal_bar_start"],
        "updated_cumulative_realized_hours": result["window"]["updated_cumulative_realized_hours"],
        "canonical_fee_bps_one_way": result["canonical_fee_bps_one_way"],
        "correction_permitted": result["training_authorized_correction"]["permitted"],
        "correction_applied": result["training_authorized_correction"]["applied"],
        "observation_epoch_restarted": result["training_authorized_correction"]["observation_epoch_restarted"],
        "abort_triggered": result["abort_conditions"]["triggered"],
        "verdict": result["verdict"],
        "paper_trading_authorized": result["paper_trading_authorized"],
        "live_trading_authorized": result["live_trading_authorized"],
    }
    report = f"""# Prospective simple-trend shadow update through 00:00 UTC on 1 August 2026

## Frozen run

- Policy: `{result["policy_name"]}`
- Policy SHA-256: `{result["policy_sha256"]}`
- Public source: anonymous OKX 1H candles
- Acquisition server time: `{result["acquisition"]["server_time"]}`
- Prior signal bar: `{result["window"]["prior_last_signal_bar_start"]}`
- Latest complete signal bar: `{result["window"]["latest_complete_signal_bar_start"]}`
- New observations: `{result["new_public_observations_per_market"]}` per market
- Elapsed period: `{result["elapsed_period_hours"]}` hour
- Cumulative realised hours: `{result["window"]["updated_cumulative_realized_hours"]}`
- Fee: exactly `{result["canonical_fee_bps_one_way"]}` bps one way
- Abort triggered: `{result["abort_conditions"]["triggered"]}`

| Market | Position | New target | Realised net | Benchmark | Residual | Turnover | Fees | 2,160H margin | Margin drift |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(rows)}

The score is prospective shadow evidence only. Cash intervals are loss avoidance or opportunity cost, not exposed alpha.

## Five-interval scorecard

| Market | Long decisions | Strategy net | Benchmark | Residual | Turnover | Fees | Max DD | Sharpe | Edge/turnover (bps) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{chr(10).join(recent_rows)}

Sharpe and edge per turnover are undefined when the frozen strategy has no return variance or turnover. Conditional-long calibration, signal decay, and loss clustering remain unassessable when the newly realised interval is cash-only.

## Drift diagnosis

- Instrument: `{discrepancy["selected_instrument"]}`
- Classification: `{discrepancy["classification"]}`
- Latest benchmark return: `{pct(discrepancy["latest_interval_asset_return"])}`
- Five-interval benchmark return: `{pct(discrepancy["five_interval_benchmark_return"])}`
- Trend-margin drift: `{pct(discrepancy["trend_margin_drift"])}`
- Policy/accounting defect detected: `{discrepancy["policy_or_accounting_defect_detected"]}`

{discrepancy["diagnosis"]}

## Candidate disposition

The separately preregistered `{active["family_id"]}` candidate is terminally rejected. XTZUSDT achieved `{pct(active["rejection_evidence"]["XTZUSDT"]["oos_net_return"])}` OOS net versus `{pct(active["rejection_evidence"]["XTZUSDT"]["trend_oos_net_return"])}` for the frozen trend benchmark. ZECUSDT achieved `{pct(active["rejection_evidence"]["ZECUSDT"]["oos_net_return"])}` versus `{pct(active["rejection_evidence"]["ZECUSDT"]["trend_oos_net_return"])}`. Each market passed only `{active["rejection_evidence"]["XTZUSDT"]["gates_passed"]}/{active["rejection_evidence"]["XTZUSDT"]["gate_count"]}` predeclared gates. Positive-fold breadth was 3/6, profit concentration was excessive, paired candidate-minus-trend uncertainty intervals crossed zero, and edge per turnover was materially below the benchmark. No same-cohort rescue, policy correction, or epoch restart is authorised.

## Verdict

```json
{json.dumps(verdict, sort_keys=True, indent=2)}
```

Next strategy-facing action: {result["next_strategy_action"]}.
"""
    (output_dir / "report.md").write_text(report)


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 574
    result["window"]["updated_cumulative_realized_hours"] = 575
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 835,
        "pull_request": 836,
        "family_id": "multi-horizon-local-linear-trend-ensemble-1h-v1",
        "status": "terminal_architecture_rejected",
        "classification": "one_candidate_executable_temporal_architecture_experiment",
        "markets": ["XTZUSDT", "ZECUSDT"],
        "candidate_count": 1,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "training_diagnostic_evaluated": True,
        "candidate_performance_evaluated": True,
        "oos_accessed": True,
        "later_data_accessed": True,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "3a3fde39e740bb672e463cc1f5c318207137d141",
        "workflow_run": 30676871217,
        "artifact_id": 8810786934,
        "artifact_sha256": "e5663cce5a70c4324768658c1384183f9a76fad06b8543a44778118484a07948",
        "verdict": "reject_multi_horizon_local_linear_trend_ensemble_architecture_v1",
        "markets_accepted": 0,
        "market_count": 2,
        "rejection_evidence": {
            "XTZUSDT": {
                "oos_net_return": 0.093397,
                "oos_sharpe": 0.4227,
                "oos_max_drawdown": -0.669163,
                "oos_turnover": 78.0,
                "trend_oos_net_return": 0.365322,
                "trend_oos_sharpe": 0.6498,
                "trend_oos_max_drawdown": -0.592077,
                "trend_oos_turnover": 4.0,
                "positive_folds": 3,
                "fold_count": 6,
                "gates_passed": 5,
                "gate_count": 13
            },
            "ZECUSDT": {
                "oos_net_return": 4.974124,
                "oos_sharpe": 1.6292,
                "oos_max_drawdown": -0.619902,
                "oos_turnover": 98.0,
                "trend_oos_net_return": 9.192189,
                "trend_oos_sharpe": 1.8846,
                "trend_oos_max_drawdown": -0.612917,
                "trend_oos_turnover": 12.0,
                "positive_folds": 3,
                "fold_count": 6,
                "gates_passed": 5,
                "gate_count": 13
            }
        },
        "reason": "positive OOS absolute returns did not outperform the frozen 2160H trend benchmark; temporal breadth, concentration, uncertainty, and edge-per-turnover gates failed bilaterally"
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": "the local-linear ensemble accepted zero of two markets and failed bilateral superiority, temporal-breadth, concentration, and edge-per-turnover gates"
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": "the new interval contains frozen long exposure and contributes conditional-long forward evidence" if exposed else "the new interval is cash-only, so it supplies no realised conditional-long return and cannot validate historical selection persistence"
    }
    result["next_strategy_action"] = "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation; do not rescue the rejected multi-horizon local-linear ensemble; separately preregister a materially orthogonal temporal rule on a fresh immutable cohort before any OOS access"
    base.write_outputs(output_dir, result)
    write_report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"))
    args = parser.parse_args()
    result = run(args.output_dir, args.base_url.rstrip("/"))
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
