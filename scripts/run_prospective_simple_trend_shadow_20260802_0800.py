from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_0700 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_646_800_000
REALIZED_DECISION_HOUR_MS = 1_785_650_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_650_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_654_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_636_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_657_600_000
PRIOR_RESULT_SHA256 = "4d0cb98cae86ab092d93e6f413668006fe0ff24813c3855715f07eb8beaedad5"
PRIOR_ARTIFACT_SHA256 = "ef0f0a686dcbb8640eebe89b2eb12b0124bbb80861293116eba67694007bdf2c"


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


def iso_utc(hour_ms: int) -> str:
    return (
        datetime.fromtimestamp(hour_ms / 1000.0, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def write_outputs(output_dir: Path, result: dict[str, Any]) -> None:
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    (output_dir / "result.json").write_text(payload)
    (output_dir / "result.sha256").write_text(
        hashlib.sha256(payload.encode()).hexdigest() + "\n"
    )

    lines = [
        "# Prospective simple-trend checkpoint through 08:00 UTC on 2 August 2026",
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
            f"{pct(recent['net_compound_return'])} | "
            f"{pct(recent['benchmark_compound_return'])} | "
            f"{pct(recent['residual_vs_buy_and_hold'])} | {recent['turnover']} | "
            f"{pct(recent['modeled_fees'])} | {pct(recent['maximum_drawdown'])} | "
            f"{recent['loss_count']} | {sharpe} | {edge} |"
        )

    lines.extend(
        [
            "",
            "## Strategy-facing finding",
            "",
            result["strategy_facing_discrepancy"]["diagnosis"],
            "",
            "The 07:00 signal bar was provider-confirmed and updated the frozen 2,160H state. "
            "The 08:00 candle supplied only its already-fixed open as the end of the 07:00–08:00 "
            "open-to-open payoff; its incomplete close, high, low and volume were excluded.",
            "",
            "The completed public-exogenous information programme closure in issue #957 / PR #958 "
            "found zero bilateral benchmark-relative, dependence-supported, breadth-and-delay-supported "
            "architecture groups. No training-authorised correction or replacement observation epoch exists.",
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
    result["window"]["prior_cumulative_realized_hours"] = 606
    result["window"]["updated_cumulative_realized_hours"] = 607
    result["performance_accessed"] = False
    result["oos_accessed"] = False
    result["machine_readable_verdict"]["updated_cumulative_realized_hours"] = 607
    result["machine_readable_verdict"]["payoff_end_open_timestamp"] = iso_utc(
        PAYOFF_END_OPEN_HOUR_MS
    )
    result["prospective_lineage"]["prior_result_sha256"] = PRIOR_RESULT_SHA256
    result["prospective_lineage"]["prior_artifact_sha256"] = PRIOR_ARTIFACT_SHA256
    result["checkpoint_replication"] = {
        "type": "new_hour_after_exact_prior_checkpoint",
        "prior_pull_request": 956,
        "prior_workflow_run": 30737484352,
        "prior_artifact_id": 8830098707,
        "prior_result_sha256": PRIOR_RESULT_SHA256,
        "prior_artifact_sha256": PRIOR_ARTIFACT_SHA256,
        "policy_unchanged": True,
        "source_contract_unchanged": True,
        "fee_unchanged": True,
    }
    result["latest_completed_programme_closure"] = {
        "family_id": "causal-public-exogenous-information-programme-closure-1h-v1",
        "issue": 957,
        "pull_request": 958,
        "tested_head": "986dd303b14cea148d29c8427ef721c43809ff21",
        "workflow_run": 30738312183,
        "artifact_id": 8830379983,
        "artifact_sha256": "d6fc5ee1dacacf776c7e87ba5245e2419471504efb0a59acae6d55e69c756086",
        "evidence_sha256": "c3ac05a6933fdfbaf616740af26fa0ef7923875f571d8ad44b59b82343486002",
        "architecture_group_count": 8,
        "direct_source_feasible_group_count": 3,
        "economically_executable_group_count": 1,
        "bilateral_benchmark_relative_support_count": 0,
        "bilateral_dependence_support_count": 0,
        "bilateral_breadth_delay_support_count": 0,
        "supportive_leave_one_out_subset_count": 0,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "new_market_data": 0,
        "new_target_returns": 0,
        "new_oos_consumed": 0,
        "verdict": "reject_reopening_completed_public_exogenous_information_mechanisms_1h_v1",
        "status": "completed_rejected_closed_without_merge",
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the completed public-exogenous information programme closure found zero "
            "bilateral benchmark-relative, dependence-supported, or breadth-and-delay-supported "
            "groups, and no materially orthogonal replacement architecture is preregistered"
        ),
    }
    result["next_strategy_action"] = (
        "advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at the "
        "next complete public 1H observation; open no replacement strategy until a materially "
        "orthogonal causal source contract and falsifiable temporal rule are frozen before "
        "feature or target-return access"
    )
    result["machine_readable_verdict"]["correction_permitted"] = False
    result["machine_readable_verdict"]["correction_applied"] = False
    result["machine_readable_verdict"]["policy_changed"] = False
    result["machine_readable_verdict"]["observation_epoch_restarted"] = False
    result["machine_readable_verdict"]["active_family_id"] = None
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
