from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_1000 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_744_000_000
REALIZED_DECISION_HOUR_MS = 1_785_747_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_747_600_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_751_200_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_733_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_754_800_000

PRIOR_RESULT_SHA256 = (
    "2635dffacb689a87dc96d800da32e8ac2c44675495eefcdc2991d4d6683cc73f"
)
PRIOR_ARTIFACT_SHA256 = (
    "43369832d629fcad66d5fd23cc42f32f49bce822c5f3e5af49d39c02f36cc98b"
)
PRIOR_PULL_REQUEST = 1048
PRIOR_WORKFLOW_RUN = 30805672882
PRIOR_ARTIFACT_ID = 8852645649
PRIOR_CUMULATIVE_REALIZED_HOURS = 633
UPDATED_CUMULATIVE_REALIZED_HOURS = 634

LATEST_ARCHITECTURE: dict[str, Any] = {
    "family_id": (
        "causal-own-price-drawdown-recovery-event-history-programme-"
        "closure-1h-v1"
    ),
    "issue": 1050,
    "pull_request": None,
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "bound_mechanism_count": 5,
    "historical_candidate_count": 4,
    "fixed_cohort_count": 3,
    "fixed_target_count": 8,
    "mechanisms_admissible": 0,
    "new_market_data_rows": 0,
    "new_target_labels": 0,
    "bilateral_pass": False,
    "target_returns_accessed": False,
    "strategy_performance_accessed": False,
    "benchmark_path_accessed": False,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_completed_family_closure",
    "verdict": (
        "reject_reopening_completed_drawdown_recovery_event_history_"
        "mechanisms_1h_v1"
    ),
    "highest_value_failure": (
        "Event prediction and turnover reduction repeatedly failed to transfer "
        "into broad, dependence-supported, fee-adjusted net alpha."
    ),
    "next_action": (
        "Do not reopen drawdown, recovery, bridge, recross, duration, peak, "
        "pseudocount, target-substitution or single-market rescue paths."
    ),
}

ACTIVE_ARCHITECTURE: dict[str, Any] = {
    "family_id": (
        "causal-own-price-bipower-jump-share-contraction-opportunity-1h-v1"
    ),
    "issue": 1051,
    "status": "preregistered_not_evaluated",
    "fixed_targets": ["NEAR-USDT", "APT-USDT"],
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "target_returns_accessed": False,
    "strategy_performance_accessed": False,
    "benchmark_path_accessed": False,
    "sealed_oos_accessed": False,
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
        "RECENT_WINDOW_FIRST_DECISION_HOUR_MS": (
            RECENT_WINDOW_FIRST_DECISION_HOUR_MS
        ),
        "RECENT_WINDOW_LAST_DECISION_HOUR_MS": (
            RECENT_WINDOW_LAST_DECISION_HOUR_MS
        ),
        "PAYOFF_END_OPEN_HOUR_MS": PAYOFF_END_OPEN_HOUR_MS,
        "PRIOR_RESULT_SHA256": PRIOR_RESULT_SHA256,
        "PRIOR_ARTIFACT_SHA256": PRIOR_ARTIFACT_SHA256,
        "PRIOR_PULL_REQUEST": PRIOR_PULL_REQUEST,
        "PRIOR_WORKFLOW_RUN": PRIOR_WORKFLOW_RUN,
        "PRIOR_ARTIFACT_ID": PRIOR_ARTIFACT_ID,
        "PRIOR_CUMULATIVE_REALIZED_HOURS": PRIOR_CUMULATIVE_REALIZED_HOURS,
        "UPDATED_CUMULATIVE_REALIZED_HOURS": UPDATED_CUMULATIVE_REALIZED_HOURS,
    }
    for name, value in assignments.items():
        setattr(checkpoint, name, value)
    checkpoint.LATEST_ARCHITECTURE = LATEST_ARCHITECTURE
    checkpoint.ACTIVE_ARCHITECTURE = ACTIVE_ARCHITECTURE
    checkpoint.configure_checkpoint()


def finalize(result: dict[str, Any]) -> dict[str, Any]:
    result = checkpoint.finalize(result)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )
    result["active_alpha_context"] = dict(LATEST_ARCHITECTURE)
    result["latest_training_only_architecture"] = dict(LATEST_ARCHITECTURE)
    result["active_strategy_architecture"] = dict(ACTIVE_ARCHITECTURE)
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "Issue 1050 terminally rejected the completed drawdown/recovery "
            "event-history programme. Issue 1051 is preregistered but unevaluated "
            "and therefore creates no correction authority."
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow "
        "at the next complete public 1H observation. Evaluate issue 1051 only "
        "under its frozen NEAR-USDT/APT-USDT bipower jump-share contraction "
        "training protocol. Do not reopen drawdown/recovery mechanisms or alter "
        "the cohort, RV/BV identity, feature sign, windows, lag, E2160 condition, "
        "fee, folds, bootstrap, delay or promotion rules after source or label "
        "access."
    )
    machine = result["machine_readable_verdict"]
    machine.update(
        {
            "updated_cumulative_realized_hours": (
                UPDATED_CUMULATIVE_REALIZED_HOURS
            ),
            "payoff_end_open_timestamp": iso_utc(PAYOFF_END_OPEN_HOUR_MS),
            "correction_permitted": False,
            "correction_applied": False,
            "policy_changed": False,
            "observation_epoch_restarted": False,
            "latest_training_diagnostic_verdict": LATEST_ARCHITECTURE[
                "verdict"
            ],
            "active_family_id": ACTIVE_ARCHITECTURE["family_id"],
            "active_family_status": ACTIVE_ARCHITECTURE["status"],
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
        }
    )
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

    window = result["window"]
    assert window["prior_last_signal_bar_start"] == "2026-08-03T09:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T10:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T10:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T11:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 633
    assert window["updated_cumulative_realized_hours"] == 634

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"]
        == "2026-08-03T10:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    latest = result["latest_training_only_architecture"]
    assert latest["issue"] == 1050
    assert latest["candidate_count"] == 0
    assert latest["parameter_grid_count"] == 0
    assert latest["sealed_oos_accessed"] is False
    assert latest["correction_authority"] is False
    assert latest["bilateral_pass"] is False

    active = result["active_strategy_architecture"]
    assert active["issue"] == 1051
    assert active["status"] == "preregistered_not_evaluated"
    assert active["candidate_count"] == 0
    assert active["parameter_grid_count"] == 0
    assert active["target_returns_accessed"] is False
    assert active["sealed_oos_accessed"] is False
    assert active["correction_authority"] is False

    correction = result["training_authorized_correction"]
    assert correction["permitted"] is False
    assert correction["applied"] is False
    assert correction["policy_changed"] is False
    assert correction["observation_epoch_restarted"] is False
    assert result["abort_conditions"]["triggered"] is False

    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T11:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 634
    assert machine["correction_permitted"] is False
    assert machine["live_trading_authorized"] is False


def persist(output_dir: Path, result: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (output_dir / "result.json").write_text(payload, encoding="utf-8")
    (output_dir / "result.sha256").write_text(digest + "\n", encoding="utf-8")
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
        "# Prospective simple-trend checkpoint through 11:00 UTC on "
        "3 August 2026\n\n"
        "The 10:00 signal bar was provider-confirmed. The 11:00 candle supplied "
        "only its fixed opening price as the payoff endpoint.\n\n"
        "The completed drawdown/recovery event-history programme remains "
        "terminally rejected. The bipower jump-share architecture in issue 1051 "
        "is preregistered but unevaluated and cannot authorise a correction.\n\n"
        "```json\n"
        + json.dumps(compact, sort_keys=True, indent=2, allow_nan=False)
        + "\n```\n\n"
        + f"Result SHA-256: `{digest}`\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return digest


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_checkpoint()
    result = checkpoint.checkpoint.checkpoint.checkpoint.call_inherited_core(
        output_dir, base_url.rstrip("/")
    )
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
