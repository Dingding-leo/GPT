from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_0800 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_736_800_000
REALIZED_DECISION_HOUR_MS = 1_785_740_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_740_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_744_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_726_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_747_600_000

PRIOR_RESULT_SHA256 = (
    "d21866a6b1ea8f55e07ec5e84ee371ec7b568390c2206191b5837a79a9b56f84"
)
PRIOR_ARTIFACT_SHA256 = (
    "8645b5139df27851a9cea2da6b1a6a5efba3ccb63517955c8d5ea8cd78d3c665"
)
PRIOR_PULL_REQUEST = 1041
PRIOR_WORKFLOW_RUN = 30797036417
PRIOR_ARTIFACT_ID = 8849294420
PRIOR_CUMULATIVE_REALIZED_HOURS = 631
UPDATED_CUMULATIVE_REALIZED_HOURS = 632

LATEST_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-own-price-recurrence-determinism-shift-opportunity-1h-v1",
    "issue": 1039,
    "pull_request": 1042,
    "exact_tested_head": "090cc4a12effa4920a1a41a4177d5cba47931e5b",
    "workflow_run": 30798724765,
    "artifact_id": 8850152615,
    "artifact_sha256": "1696ba79aab52ed194a8d8b1c74e7d4201cb6a0975c8661a276850222a2d98e6",
    "evidence_sha256": "5227d0387be0501961d1f8fa974251c7237e8b0f57f31ee66c1d7fd9f670938e",
    "report_sha256": "3707fdfdc75845abe98829883b80e80bdc7979d9b2dad53fc1ca91d9c9a3cc47",
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "bilateral_pass": False,
    "target_returns_accessed": True,
    "strategy_performance_accessed": False,
    "benchmark_path_accessed": False,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_training_information_premise",
    "verdict": (
        "reject_causal_own_price_recurrence_determinism_shift_"
        "information_premise_1h_v1"
    ),
    "highest_value_failure": (
        "BTC had weak favourable point effects but failed dependence and fold-breadth "
        "support; ETH contradicted the frozen continuation premise and remained "
        "adverse after the one-hour-delay replay."
    ),
    "next_action": (
        "Do not reopen recurrence thresholds, embeddings, metrics, Theiler windows, "
        "line lengths, windows, normalisations, signs, targets or favourable periods."
    ),
}

ACTIVE_ARCHITECTURE: dict[str, Any] = {
    "family_id": (
        "causal-own-price-horizontal-visibility-path-simplification-"
        "opportunity-1h-v1"
    ),
    "issue": 1043,
    "status": "preregistered_not_evaluated",
    "fixed_targets": ["SOL-USDT", "BNB-USDT"],
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
    }
    for name, value in assignments.items():
        setattr(checkpoint, name, value)
    checkpoint.configure_checkpoint(LATEST_ARCHITECTURE, ACTIVE_ARCHITECTURE)


def finalize(result: dict[str, Any]) -> dict[str, Any]:
    result = checkpoint.finalize(
        result, LATEST_ARCHITECTURE, ACTIVE_ARCHITECTURE
    )
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["active_alpha_context"] = dict(LATEST_ARCHITECTURE)
    result["latest_training_only_architecture"] = dict(LATEST_ARCHITECTURE)
    result["active_strategy_architecture"] = dict(ACTIVE_ARCHITECTURE)
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "The latest recurrence-determinism information premise was rejected "
            "bilaterally. Issue 1043 is preregistered but has not been evaluated and "
            "therefore creates no correction authority."
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Evaluate issue 1043 only under "
        "its frozen SOL-USDT/BNB-USDT horizontal-visibility information protocol. "
        "Do not reopen the rejected recurrence-determinism family or alter visibility "
        "definitions, windows, signs, graph statistics, target cohort, chronology, "
        "fee, folds, bootstrap, delay or promotion rules after source or label access."
    )
    machine = result["machine_readable_verdict"]
    machine["updated_cumulative_realized_hours"] = UPDATED_CUMULATIVE_REALIZED_HOURS
    machine["payoff_end_open_timestamp"] = iso_utc(PAYOFF_END_OPEN_HOUR_MS)
    machine["correction_permitted"] = False
    machine["correction_applied"] = False
    machine["policy_changed"] = False
    machine["observation_epoch_restarted"] = False
    machine["latest_training_diagnostic_verdict"] = LATEST_ARCHITECTURE["verdict"]
    machine["active_family_id"] = ACTIVE_ARCHITECTURE["family_id"]
    machine["active_family_status"] = ACTIVE_ARCHITECTURE["status"]
    machine["paper_trading_authorized"] = False
    machine["live_trading_authorized"] = False
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
    assert window["prior_last_signal_bar_start"] == "2026-08-03T07:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T08:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T08:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T09:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 631
    assert window["updated_cumulative_realized_hours"] == 632

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"]
        == "2026-08-03T08:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    latest = result["latest_training_only_architecture"]
    assert latest["issue"] == 1039
    assert latest["pull_request"] == 1042
    assert latest["candidate_count"] == 0
    assert latest["parameter_grid_count"] == 0
    assert latest["sealed_oos_accessed"] is False
    assert latest["correction_authority"] is False
    assert latest["bilateral_pass"] is False

    active = result["active_strategy_architecture"]
    assert active["issue"] == 1043
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
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T09:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 632
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
        "# Prospective simple-trend checkpoint through 09:00 UTC on 3 August 2026\n\n"
        "The 08:00 signal bar was provider-confirmed. The 09:00 candle supplied "
        "only its fixed opening price as the payoff endpoint.\n\n"
        "The latest completed recurrence-determinism information premise remains "
        "terminally rejected. The horizontal-visibility architecture in issue 1043 "
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
    result = checkpoint.checkpoint.call_inherited_core(
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
