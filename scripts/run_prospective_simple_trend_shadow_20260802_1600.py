from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_1500 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_675_600_000
REALIZED_DECISION_HOUR_MS = 1_785_679_200_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_679_200_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_682_800_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_664_800_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_686_400_000

PRIOR_RESULT_SHA256 = "14794768e932aaaa77b3fc942a82315954c17b1cd2269635bdc38d53e7af0db4"
PRIOR_ARTIFACT_SHA256 = "611081d77845686d3ad9261f7be92a24b2741b889041ae4cbbdf4f4d9de81b00"
PRIOR_PULL_REQUEST = 981
PRIOR_WORKFLOW_RUN = 30754246815
PRIOR_ARTIFACT_ID = 8835418274
PRIOR_CUMULATIVE_REALIZED_HOURS = 614
UPDATED_CUMULATIVE_REALIZED_HOURS = 615


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


def metric(value: float | None, digits: int = 6) -> str:
    if value is None:
        return "undefined"
    return f"{value:.{digits}f}"


def write_result(output_dir: Path, result: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    (output_dir / "result.json").write_text(payload)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (output_dir / "result.sha256").write_text(digest + "\n")


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    window = result["window"]
    discrepancy = result["strategy_facing_discrepancy"]
    machine = result["machine_readable_verdict"]
    closure = result["latest_training_only_architecture"]

    lines = [
        "# Prospective simple-trend checkpoint through 16:00 UTC on 2 August 2026",
        "",
        f"- Policy: `{result['policy_name']}`",
        f"- Acquisition server time: `{result['acquisition']['server_time']}`",
        f"- Latest complete signal bar: `{window['latest_complete_signal_bar_start']}`",
        (
            "- Realised payoff interval: "
            f"`{window['realized_payoff_interval_start']}` to "
            f"`{window['realized_payoff_interval_end']}`"
        ),
        f"- Cumulative realised hours: `{window['updated_cumulative_realized_hours']}`",
        f"- Fee: exactly `{result['canonical_fee_bps_one_way']}` bps one way",
        f"- Abort: `{result['abort_conditions']['triggered']}`",
        "",
        "| Market | Carried position | New target | Expected / realised net | Benchmark | Residual | Turnover | Fees | New 2160H margin | Margin drift |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for market in result["markets"]:
        realised = market["realized_interval"]
        decision = market["new_decisions"][0]
        drift = market["signal_drift"]["margin_change"]
        lines.append(
            "| {instrument} | {position} | {target} | {expected} / {realized} | "
            "{benchmark} | {residual} | {turnover} | {fee} | {margin} | {drift} |".format(
                instrument=market["instrument"],
                position="Long" if realised["position"] else "Cash",
                target="Long" if decision["target"] else "Cash",
                expected=pct(realised["expected_net_return_under_frozen_decision"]),
                realized=pct(realised["net_strategy_return"]),
                benchmark=pct(realised["asset_return"]),
                residual=pct(realised["strategy_residual_vs_buy_and_hold"]),
                turnover=realised["turnover"],
                fee=pct(realised["modeled_fee"]),
                margin=pct(decision["margin"]),
                drift=pct(drift),
            )
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
        lines.append(
            "| {instrument} | {longs}/{count} | {net} | {benchmark} | {residual} | "
            "{turnover} | {fees} | {max_dd} | {losses} | {sharpe} | {edge} |".format(
                instrument=market["instrument"],
                longs=recent["long_decision_count"],
                count=recent["realized_interval_count"],
                net=pct(recent["net_compound_return"]),
                benchmark=pct(recent["benchmark_compound_return"]),
                residual=pct(recent["residual_vs_buy_and_hold"]),
                turnover=metric(recent["turnover"]),
                fees=pct(recent["modeled_fees"]),
                max_dd=pct(recent["maximum_drawdown"]),
                losses=recent["loss_count"],
                sharpe=metric(recent["sharpe"]),
                edge=metric(recent["edge_per_turnover_bps"]),
            )
        )

    selected = next(
        market
        for market in result["markets"]
        if market["instrument"] == discrepancy["selected_instrument"]
    )
    attribution = selected["drift_attribution"]
    lines.extend(
        [
            "",
            "## Strategy-facing finding",
            "",
            (
                "Selected discrepancy: "
                f"`{discrepancy['selected_instrument']}` / "
                f"`{discrepancy['classification']}`."
            ),
            "",
            f"Latest benchmark return: `{pct(discrepancy['latest_interval_asset_return'])}`.",
            (
                "Five-interval benchmark return: "
                f"`{pct(discrepancy['five_interval_benchmark_return'])}`."
            ),
            f"E2160 margin drift: `{pct(discrepancy['trend_margin_drift'])}`.",
            f"Completed-close return: `{pct(attribution['current_close_return'])}`.",
            (
                "Advancing 2,160-hour reference return: "
                f"`{pct(attribution['lagged_reference_return'])}`."
            ),
            "",
            discrepancy["diagnosis"],
            "",
            (
                "The 15:00 signal bar was provider-confirmed and updated only the frozen "
                "per-instrument 2,160-hour state. The 16:00 candle supplied only its "
                "already-fixed opening price as the endpoint of the 15:00–16:00 "
                "open-to-open payoff. Its incomplete close, high, low and volume were "
                "excluded from every signal, feature, target, position, turnover and fee "
                "calculation."
            ),
            "",
            "## Correction disposition",
            "",
            (
                "The completed conditional-variance-state programme closure in PR #982 "
                "bound eight consumed own-price risk-state mechanism groups and found zero "
                "bilaterally supported groups, zero supportive leave-one-group-out subsets, "
                "candidate count zero and no correction authority. No active replacement "
                "architecture or newly frozen observation epoch exists."
            ),
            "",
            f"- Closure family: `{closure['family_id']}`",
            f"- Closure verdict: `{closure['verdict']}`",
            f"- Correction permitted/applied: `{machine['correction_permitted']}` / `{machine['correction_applied']}`",
            f"- Canonical policy changed: `{machine['policy_changed']}`",
            f"- Observation epoch restarted: `{machine['observation_epoch_restarted']}`",
            f"- Paper trading authorised: `{machine['paper_trading_authorized']}`",
            f"- Live trading authorised: `{machine['live_trading_authorized']}`",
            "",
            "```json",
            json.dumps(machine, sort_keys=True, indent=2, allow_nan=False),
            "```",
            "",
            "Next strategy-facing action: " + result["next_strategy_action"] + ".",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["window"]["prior_cumulative_realized_hours"] = PRIOR_CUMULATIVE_REALIZED_HOURS
    result["window"]["updated_cumulative_realized_hours"] = UPDATED_CUMULATIVE_REALIZED_HOURS
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
        "family_id": "causal-own-price-conditional-variance-state-programme-closure-1h-v1",
        "pull_request": 982,
        "exact_tested_head": "f58eacb00cbdbf396a97b896f271e777cb3175ed",
        "workflow_run": 30755072950,
        "artifact_id": 8835663204,
        "artifact_sha256": "ffa23b0d6a83376ebd087a8a59220c3ceef396686381a22662111f1d2ef8a2dc",
        "bound_mechanism_groups": 8,
        "bilateral_supported_groups": 0,
        "supportive_leave_one_group_out_subsets": 0,
        "targets_passing": 0,
        "target_count": 2,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "sealed_oos_accessed": False,
        "verdict": "reject_reopening_completed_conditional_variance_state_mechanisms_1h_v1",
        "correction_authority": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the completed conditional-variance-state programme closure found zero "
            "bilaterally supported groups, zero supportive leave-one-group-out subsets, "
            "candidate count zero and no active replacement architecture"
        ),
    }
    result["next_strategy_action"] = (
        "advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation; do not reopen the completed "
        "conditional-variance-state mechanisms, and freeze any materially orthogonal "
        "causal source contract and falsifiable temporal rule before feature or "
        "target-return access"
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
