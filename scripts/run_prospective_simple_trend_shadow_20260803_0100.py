from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_0000 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_708_000_000
REALIZED_DECISION_HOUR_MS = 1_785_711_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_711_600_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_715_200_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_697_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_718_800_000

PRIOR_RESULT_SHA256 = (
    "3358ead679af67d159ca3160b68b735cc1359e87e48611a51600ce30f47b8260"
)
PRIOR_ARTIFACT_SHA256 = (
    "72d84d0ddf70d11bb457b3ab1dbdd2fc354c44003b89dc84284aea49d010bbd6"
)
PRIOR_PULL_REQUEST = 1011
PRIOR_WORKFLOW_RUN = 30774211612
PRIOR_ARTIFACT_ID = 8841462457
PRIOR_CUMULATIVE_REALIZED_HOURS = 623
UPDATED_CUMULATIVE_REALIZED_HOURS = 624

LATEST_TRAINING_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-target-innovation-hysteresis-fixed-cohort-replication-1h-v1",
    "issue": 1010,
    "pull_request": 1012,
    "exact_tested_head": "8414ed390e6d4d7dc6364a2c4ba316dfeb3789d0",
    "workflow_run": 30775167811,
    "artifact_id": 8841846457,
    "artifact_sha256": (
        "632e737777caeaa4d159dbcaeca7d2e4aa1610624066dd779436ceb11a72c267"
    ),
    "evidence_sha256": (
        "a1995198534aad7e56dd630d08b69ad9b5fddec20fbd04da6387628f6751367a"
    ),
    "report_sha256": (
        "2afe3e5184f31f7dc096293d431098cff7752f2558140a874e5dba073c9b3298"
    ),
    "policy_contract_sha256": (
        "e22ef8616711d665c569cb74bf6932c74f0a9847332d769c9f47b59628c7615c"
    ),
    "source_contract_passed": True,
    "candidate_count": 1,
    "parameter_grid_count": 0,
    "targets_passing": 0,
    "target_count": 2,
    "target_returns_accessed": True,
    "development_oos_accessed": True,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_candidate",
    "verdict": (
        "reject_causal_target_innovation_hysteresis_fixed_cohort_replication_1h_v1"
    ),
    "target_summary": {
        "ADA-USDT": {
            "passed": False,
            "training_h1_net_return": -0.24025641590673752,
            "oos_h1_net_return": 0.06710265039964769,
            "full_h1_net_return": -0.18927560778994834,
            "oos_h1_sharpe": 0.21028597211196262,
            "oos_h1_turnover": 103.29917748903,
            "oos_h1_fees": 0.051649588744515,
            "positive_relative_folds": 8,
            "profitable_folds": 4,
        },
        "XRP-USDT": {
            "passed": False,
            "training_h1_net_return": -0.12773723384814129,
            "oos_h1_net_return": -0.15578166595241372,
            "full_h1_net_return": -0.26361978070753744,
            "oos_h1_sharpe": -0.16411335425949025,
            "oos_h1_turnover": 127.73651281911484,
            "oos_h1_fees": 0.06386825640955743,
            "positive_relative_folds": 10,
            "profitable_folds": 5,
        },
    },
    "highest_value_failure": (
        "The frozen target-innovation hysteresis reduced turnover and fees and "
        "improved relative return and Sharpe, but failed bilateral absolute "
        "economics and breadth. ADA remained negative in training and full sample; "
        "XRP remained negative in training, OOS and full sample and also failed "
        "dependence and one-hour-delay support."
    ),
    "strategy_facing_conclusion": (
        "The innovation band suppresses low-information target changes, but its "
        "benefit is mostly transaction-cost compression rather than a persistent "
        "positive return relationship across fixed independent targets."
    ),
}


def iso_utc(hour_ms: int) -> str:
    return (
        datetime.fromtimestamp(hour_ms / 1000.0, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def configure_checkpoint() -> None:
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
        setattr(checkpoint, name, globals()[name])


def call_inherited_checkpoint(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_checkpoint()
    return checkpoint.call_inherited_checkpoint(output_dir, base_url.rstrip("/"))


def finalize(result: dict[str, Any]) -> dict[str, Any]:
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["performance_accessed"] = False
    result["oos_accessed"] = False

    window = result["window"]
    window["prior_cumulative_realized_hours"] = PRIOR_CUMULATIVE_REALIZED_HOURS
    window["updated_cumulative_realized_hours"] = UPDATED_CUMULATIVE_REALIZED_HOURS

    result["prospective_lineage"]["prior_result_sha256"] = PRIOR_RESULT_SHA256
    result["prospective_lineage"]["prior_artifact_sha256"] = PRIOR_ARTIFACT_SHA256
    result["checkpoint_replication"] = {
        "prior_pull_request": PRIOR_PULL_REQUEST,
        "prior_workflow_run": PRIOR_WORKFLOW_RUN,
        "prior_artifact_id": PRIOR_ARTIFACT_ID,
        "prior_result_sha256": PRIOR_RESULT_SHA256,
        "prior_artifact_sha256": PRIOR_ARTIFACT_SHA256,
        "policy_unchanged": True,
        "source_contract_unchanged": True,
        "fee_unchanged": True,
    }

    architecture = dict(LATEST_TRAINING_ARCHITECTURE)
    result["active_alpha_context"] = architecture
    result["latest_training_only_architecture"] = architecture
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the fixed-cohort ADA/XRP target-innovation hysteresis replication "
            "failed bilateral absolute-return, breadth and robustness gates; its "
            "terminal rejection created no correction authority"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Do not rescue the rejected "
        "target-innovation hysteresis rule through another band width, target "
        "cohort, fee interpretation, delay, fold selection or target subset. "
        "Freeze a materially orthogonal causal rule before feature or target-return "
        "access."
    )

    machine = result["machine_readable_verdict"]
    machine["updated_cumulative_realized_hours"] = UPDATED_CUMULATIVE_REALIZED_HOURS
    machine["payoff_end_open_timestamp"] = iso_utc(PAYOFF_END_OPEN_HOUR_MS)
    machine["correction_permitted"] = False
    machine["correction_applied"] = False
    machine["policy_changed"] = False
    machine["observation_epoch_restarted"] = False
    machine["active_family_id"] = None
    machine["active_family_status"] = "none"
    machine["latest_training_diagnostic_verdict"] = architecture["verdict"]

    return result


def validate(result: dict[str, Any]) -> None:
    assert result["policy_name"] == "simple_trend_long_cash_2160h_next_open"
    assert result["policy_sha256"] == (
        "9dc8ab03368b61546a6ae7674f1f4127953404900ff1e09e066ecf9adf741131"
    )
    assert result["bar"] == "1H"
    assert result["canonical_fee_bps_one_way"] == 5.0
    assert result["cross_sectional_selection"] is False
    assert result["actual_orders"] is False
    assert result["credentials_used"] is False
    assert result["private_endpoints_used"] is False
    assert result["enabled_adapters"] is False
    assert result["paper_trading_authorized"] is False
    assert result["live_trading_authorized"] is False
    assert result["performance_accessed"] is False
    assert result["oos_accessed"] is False

    window = result["window"]
    assert window["prior_last_signal_bar_start"] == "2026-08-02T23:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T00:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T00:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T01:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 623
    assert window["updated_cumulative_realized_hours"] == 624

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-03T00:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    architecture = result["latest_training_only_architecture"]
    assert architecture["issue"] == 1010
    assert architecture["pull_request"] == 1012
    assert architecture["exact_tested_head"] == (
        "8414ed390e6d4d7dc6364a2c4ba316dfeb3789d0"
    )
    assert architecture["workflow_run"] == 30775167811
    assert architecture["artifact_id"] == 8841846457
    assert architecture["source_contract_passed"] is True
    assert architecture["candidate_count"] == 1
    assert architecture["parameter_grid_count"] == 0
    assert architecture["targets_passing"] == 0
    assert architecture["target_count"] == 2
    assert architecture["target_returns_accessed"] is True
    assert architecture["sealed_oos_accessed"] is False
    assert architecture["canonical_strategy_changed"] is False
    assert architecture["correction_authority"] is False

    correction = result["training_authorized_correction"]
    assert correction["permitted"] is False
    assert correction["applied"] is False
    assert correction["policy_changed"] is False
    assert correction["observation_epoch_restarted"] is False
    assert result["abort_conditions"]["triggered"] is False

    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T01:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 624
    assert machine["correction_permitted"] is False
    assert machine["policy_changed"] is False
    assert machine["live_trading_authorized"] is False


def persist(output_dir: Path, result: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    digest = hashlib.sha256(payload.encode()).hexdigest()
    (output_dir / "result.json").write_text(payload)
    (output_dir / "result.sha256").write_text(digest + "\n")

    compact = {
        "policy": result["policy_name"],
        "policy_sha256": result["policy_sha256"],
        "fee_bps_one_way": result["canonical_fee_bps_one_way"],
        "acquisition": result["acquisition"],
        "window": result["window"],
        "aggregate": result["aggregate_forward_scorecard"],
        "markets": result["markets"],
        "discrepancy": result["strategy_facing_discrepancy"],
        "latest_training_only_architecture": result[
            "latest_training_only_architecture"
        ],
        "correction": result["training_authorized_correction"],
        "abort": result["abort_conditions"],
        "verdict": result["verdict"],
        "next_action": result["next_strategy_action"],
    }
    report = (
        "# Prospective simple-trend checkpoint through 01:00 UTC on 3 August 2026\n\n"
        "The 00:00 signal bar was provider-confirmed. The 01:00 candle supplied "
        "only its fixed opening price as the payoff endpoint.\n\n"
        "```json\n"
        + json.dumps(compact, sort_keys=True, indent=2, allow_nan=False)
        + "\n```\n\n"
        + f"Result SHA-256: `{digest}`\n"
    )
    (output_dir / "report.md").write_text(report)
    return digest


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    result = call_inherited_checkpoint(output_dir, base_url)
    result = finalize(result)
    validate(result)
    persist(output_dir, result)
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
            run(args.output_dir, args.base_url),
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
