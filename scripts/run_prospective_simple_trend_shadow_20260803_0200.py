from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_0100 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_711_600_000
REALIZED_DECISION_HOUR_MS = 1_785_715_200_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_715_200_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_718_800_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_700_800_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_722_400_000

PRIOR_RESULT_SHA256 = (
    "311a880f5e4f961bb3c5639aa7d21a97b485e86dd6b9d9f833c262985f114c7b"
)
PRIOR_ARTIFACT_SHA256 = (
    "ab15cc503a9f3f7ecf6317d792d2cbd57b67f37539d9945b9f3786546501bb8c"
)
PRIOR_PULL_REQUEST = 1014
PRIOR_WORKFLOW_RUN = 30776557493
PRIOR_ARTIFACT_ID = 8842228804
PRIOR_CUMULATIVE_REALIZED_HOURS = 624
UPDATED_CUMULATIVE_REALIZED_HOURS = 625

LATEST_TRAINING_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-target-innovation-hysteresis-programme-closure-1h-v1",
    "issue": 1013,
    "pull_request": 1015,
    "exact_tested_head": "faa07687ae281fc4446878906599d523776c3954",
    "workflow_run": 30777599303,
    "artifact_id": 8842562632,
    "artifact_sha256": (
        "a1b699e9be828771102ac58303a7bcd64cbaadfdcbf739a3cb42764a1493c101"
    ),
    "evidence_sha256": (
        "7308a10ae3d9788437c33a24c1e05f28f926a3d3d60c18730e7898a21d18f1ad"
    ),
    "report_sha256": (
        "e096a871f413b3695e68bc67b2a35590dcc19e788ff68afd4a4989e77833b906"
    ),
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "historical_overlay_candidates": 1,
    "closure_gate_pass_count": 2,
    "closure_gate_total": 10,
    "target_returns_accessed": False,
    "new_market_data_rows": 0,
    "new_target_labels": 0,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_programme_closure",
    "verdict": (
        "reject_reopening_completed_target_innovation_hysteresis_mechanisms_1h_v1"
    ),
    "highest_value_failure": (
        "The exact target-innovation hysteresis policy transferred as execution "
        "smoothing but not as independent alpha: ADA remained negative in training "
        "and full sample, XRP remained negative in training, OOS and full sample, "
        "fold/year breadth and dependence failed externally, and the strongest "
        "binary E2160 trend target had zero target innovations to suppress."
    ),
    "strategy_facing_conclusion": (
        "The programme is closed. Turnover compression is target-path-specific and "
        "does not authorize a replacement strategy, another band search, target "
        "subset, cohort rescue or observation-epoch restart."
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
            "the exact target-innovation hysteresis programme closure retained only "
            "target-path-specific turnover compression and rejected independent alpha "
            "across development and fixed external replication cohorts"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Do not reopen the completed "
        "target-innovation hysteresis programme through another band, target cohort, "
        "delay, fee interpretation, fold selection, target subset or smoothing rule. "
        "Freeze a materially orthogonal causal source contract and falsifiable "
        "per-instrument temporal rule before feature or target-return access."
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
    assert window["prior_last_signal_bar_start"] == "2026-08-03T00:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T01:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T01:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T02:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 624
    assert window["updated_cumulative_realized_hours"] == 625

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-03T01:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    architecture = result["latest_training_only_architecture"]
    assert architecture["issue"] == 1013
    assert architecture["pull_request"] == 1015
    assert architecture["exact_tested_head"] == (
        "faa07687ae281fc4446878906599d523776c3954"
    )
    assert architecture["workflow_run"] == 30777599303
    assert architecture["artifact_id"] == 8842562632
    assert architecture["candidate_count"] == 0
    assert architecture["parameter_grid_count"] == 0
    assert architecture["closure_gate_pass_count"] == 2
    assert architecture["closure_gate_total"] == 10
    assert architecture["target_returns_accessed"] is False
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
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T02:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 625
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
        "# Prospective simple-trend checkpoint through 02:00 UTC on 3 August 2026\n\n"
        "The 01:00 signal bar was provider-confirmed. The 02:00 candle supplied "
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
