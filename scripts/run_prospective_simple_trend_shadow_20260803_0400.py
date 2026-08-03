from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_0300 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_718_800_000
REALIZED_DECISION_HOUR_MS = 1_785_722_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_722_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_726_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_708_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_729_600_000

PRIOR_RESULT_SHA256 = (
    "806b596efd4b661d72e3a4ad7700e9ceb3c43ba03653b8b9b3c2605e147149a1"
)
PRIOR_ARTIFACT_SHA256 = (
    "667631b386edf7de7316aaf8eb49c78f57a89988fe1b239d27751d047b2f8dcd"
)
PRIOR_PULL_REQUEST = 1020
PRIOR_WORKFLOW_RUN = 30781599339
PRIOR_ARTIFACT_ID = 8843841109
PRIOR_CUMULATIVE_REALIZED_HOURS = 626
UPDATED_CUMULATIVE_REALIZED_HOURS = 627

LATEST_TRAINING_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-fixed-cohort-conformal-trend-utility-selector-1h-v1",
    "issue": 1019,
    "pull_request": 1021,
    "exact_tested_head": "67216eca1b97bcf38ff8d3ed05f10953c79437f9",
    "workflow_run": 30782993273,
    "artifact_id": 8844371870,
    "artifact_sha256": (
        "60315708142ef3ecca9950d5556062fca2ef9adcbde4bb5001b6e2d0555322ff"
    ),
    "evidence_sha256": (
        "0b5a4646d990b1d2f89e6590e286980fe00fe0f4b15bf59fb2e8a8d4ad566b7a"
    ),
    "candidate_count": 1,
    "parameter_grid_count": 0,
    "executed_candidate_count": 0,
    "source_arm_count": 2,
    "source_arms_passing": 2,
    "rows_per_target": 43_941,
    "targets": {
        "BCH-USDT": {
            "positive_model_fit_anchor_count": 39,
            "calibration_count": 132,
        },
        "LINK-USDT": {
            "positive_model_fit_anchor_count": 62,
            "calibration_count": 99,
        },
    },
    "minimum_positive_model_fit_anchors": 80,
    "labels_accessed": False,
    "performance_accessed": False,
    "benchmark_path_accessed": False,
    "oos_accessed": False,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_support_gate",
    "verdict": "reject_causal_fixed_cohort_conformal_trend_utility_selector_1h_v1",
    "highest_value_failure": (
        "Both anonymous public 1H source arms passed, but the preregistered minimum "
        "of 80 positive E2160 model-fit anchors failed bilaterally: BCH had 39 and "
        "LINK had 62. The experiment stopped before label, PAVA, conformal, candidate, "
        "benchmark, OOS or full-sample performance access."
    ),
    "strategy_facing_conclusion": (
        "Sparse positive-trend support prevents a causally calibrated fee-clearing "
        "utility lower bound on the frozen external cohort and creates no correction "
        "or observation-epoch restart authority."
    ),
}

ACTIVE_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-own-history-label-trained-selector-programme-closure-1h-v1",
    "issue": 1022,
    "status": "preregistered_zero_candidate_evidence_closure",
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "new_market_data_rows": 0,
    "new_target_labels": 0,
    "new_oos_access": False,
    "correction_authority": False,
    "canonical_mutation_authorized": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
}


def iso_utc(hour_ms: int) -> str:
    return (
        datetime.fromtimestamp(hour_ms / 1000.0, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def configure_checkpoint() -> None:
    assignments = {
        "PREVIOUS_DECISION_HOUR_MS": PREVIOUS_DECISION_HOUR_MS,
        "REALIZED_DECISION_HOUR_MS": REALIZED_DECISION_HOUR_MS,
        "PRIOR_REPORTED_SIGNAL_HOUR_MS": PRIOR_REPORTED_SIGNAL_HOUR_MS,
        "LATEST_COMPLETE_SIGNAL_HOUR_MS": LATEST_COMPLETE_SIGNAL_HOUR_MS,
        "RECENT_WINDOW_FIRST_DECISION_HOUR_MS": RECENT_WINDOW_FIRST_DECISION_HOUR_MS,
        "RECENT_WINDOW_LAST_DECISION_HOUR_MS": RECENT_WINDOW_LAST_DECISION_HOUR_MS,
        "PAYOFF_END_OPEN_HOUR_MS": PAYOFF_END_OPEN_HOUR_MS,
        "PRIOR_RESULT_SHA256": PRIOR_RESULT_SHA256,
        "PRIOR_ARTIFACT_SHA256": PRIOR_ARTIFACT_SHA256,
        "PRIOR_PULL_REQUEST": PRIOR_PULL_REQUEST,
        "PRIOR_WORKFLOW_RUN": PRIOR_WORKFLOW_RUN,
        "PRIOR_ARTIFACT_ID": PRIOR_ARTIFACT_ID,
        "PRIOR_CUMULATIVE_REALIZED_HOURS": PRIOR_CUMULATIVE_REALIZED_HOURS,
        "UPDATED_CUMULATIVE_REALIZED_HOURS": UPDATED_CUMULATIVE_REALIZED_HOURS,
        "LATEST_TRAINING_ARCHITECTURE": LATEST_TRAINING_ARCHITECTURE,
    }
    for name, value in assignments.items():
        setattr(checkpoint, name, value)


def finalize(result: dict[str, Any]) -> dict[str, Any]:
    configure_checkpoint()
    result = checkpoint.finalize(result)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["active_alpha_context"] = dict(LATEST_TRAINING_ARCHITECTURE)
    result["latest_training_only_architecture"] = dict(LATEST_TRAINING_ARCHITECTURE)
    result["active_strategy_architecture"] = dict(ACTIVE_ARCHITECTURE)
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the latest frozen conformal selector failed the bilateral support gate "
            "before labels or performance, while issue 1022 is a zero-candidate "
            "completed-family evidence closure"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Complete issue #1022 using only "
        "immutable prior evidence; do not rescue the rejected conformal selector "
        "through another cohort, confidence level, calibration refresh, fit threshold, "
        "label, horizon or target subset. Freeze a materially orthogonal causal source "
        "contract and per-instrument temporal rule before any new feature or target access."
    )
    machine = result["machine_readable_verdict"]
    machine["updated_cumulative_realized_hours"] = UPDATED_CUMULATIVE_REALIZED_HOURS
    machine["payoff_end_open_timestamp"] = iso_utc(PAYOFF_END_OPEN_HOUR_MS)
    machine["correction_permitted"] = False
    machine["correction_applied"] = False
    machine["policy_changed"] = False
    machine["observation_epoch_restarted"] = False
    machine["active_family_id"] = ACTIVE_ARCHITECTURE["family_id"]
    machine["active_family_status"] = ACTIVE_ARCHITECTURE["status"]
    machine["latest_training_diagnostic_verdict"] = LATEST_TRAINING_ARCHITECTURE[
        "verdict"
    ]
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

    window = result["window"]
    assert window["prior_last_signal_bar_start"] == "2026-08-03T02:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T03:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T03:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T04:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 626
    assert window["updated_cumulative_realized_hours"] == 627

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-03T03:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    architecture = result["latest_training_only_architecture"]
    assert architecture["issue"] == 1019
    assert architecture["pull_request"] == 1021
    assert architecture["source_arms_passing"] == 2
    assert architecture["executed_candidate_count"] == 0
    assert architecture["targets"]["BCH-USDT"]["positive_model_fit_anchor_count"] == 39
    assert architecture["targets"]["LINK-USDT"]["positive_model_fit_anchor_count"] == 62
    assert architecture["labels_accessed"] is False
    assert architecture["performance_accessed"] is False
    assert architecture["correction_authority"] is False

    active = result["active_strategy_architecture"]
    assert active["issue"] == 1022
    assert active["candidate_count"] == 0
    assert active["correction_authority"] is False

    correction = result["training_authorized_correction"]
    assert correction["permitted"] is False
    assert correction["applied"] is False
    assert correction["policy_changed"] is False
    assert correction["observation_epoch_restarted"] is False
    assert result["abort_conditions"]["triggered"] is False

    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T04:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 627
    assert machine["correction_permitted"] is False
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
        "active_strategy_architecture": result["active_strategy_architecture"],
        "correction": result["training_authorized_correction"],
        "abort": result["abort_conditions"],
        "verdict": result["verdict"],
        "next_action": result["next_strategy_action"],
    }
    report = (
        "# Prospective simple-trend checkpoint through 04:00 UTC on 3 August 2026\n\n"
        "The 03:00 signal bar was provider-confirmed. The 04:00 candle supplied "
        "only its fixed opening price as the payoff endpoint.\n\n"
        "```json\n"
        + json.dumps(compact, sort_keys=True, indent=2, allow_nan=False)
        + "\n```\n\n"
        + f"Result SHA-256: `{digest}`\n"
    )
    (output_dir / "report.md").write_text(report)
    return digest


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_checkpoint()
    result = checkpoint.call_inherited_checkpoint(output_dir, base_url.rstrip("/"))
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
    print(json.dumps(run(args.output_dir, args.base_url), sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
