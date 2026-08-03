from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_0200 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_715_200_000
REALIZED_DECISION_HOUR_MS = 1_785_718_800_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_718_800_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_722_400_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_704_400_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_726_000_000

PRIOR_RESULT_SHA256 = (
    "09eda45304655a19fb284a221fa4d5ece4f1f1ff1fab27e009d7d8de9ada9aa6"
)
PRIOR_ARTIFACT_SHA256 = (
    "7243dc3741df364b8a291556832c873d2a7f4bb75f7ebadc1688ab7eb71e55d1"
)
PRIOR_PULL_REQUEST = 1017
PRIOR_WORKFLOW_RUN = 30778991364
PRIOR_ARTIFACT_ID = 8842999259
PRIOR_CUMULATIVE_REALIZED_HOURS = 625
UPDATED_CUMULATIVE_REALIZED_HOURS = 626

LATEST_TRAINING_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-long-cash-transition-smoothing-programme-closure-1h-v1",
    "issue": 1016,
    "pull_request": 1018,
    "exact_tested_head": "922bde13ceb8248184903053c4e4c64af6aa0279",
    "workflow_run": 30779885484,
    "artifact_id": 8843273000,
    "artifact_sha256": (
        "7de93ecba657355903fb3ab1ef075ebf984126065e39572f68d541765f6f4bf3"
    ),
    "evidence_sha256": (
        "ee8bc2c0133cda92f3a20aa4eb0a36a78fb9b2999ac06161cd1ad9f7d1ed0658"
    ),
    "report_sha256": (
        "4aecfd8b40c0eb20aa7f7db3198147af1596d331c29e6c6c2fe449b10404bff9"
    ),
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "bound_mechanism_groups": 7,
    "supportive_group_count": 0,
    "closure_gate_pass_count": 1,
    "closure_gate_total": 12,
    "performance_accessed": False,
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
        "reject_reopening_completed_long_cash_transition_smoothing_mechanisms_1h_v1"
    ),
    "highest_value_failure": (
        "Across seven completed transition-smoothing mechanism groups, zero passed "
        "their original bilateral promotion gates and every leave-one-group-out "
        "subset retained zero support. Scalar no-trade regions delayed valuable "
        "regime changes, preserved harmful exposure, or reduced revisions on an "
        "upstream target that was itself weak."
    ),
    "strategy_facing_conclusion": (
        "The transition-smoothing programme is closed. Smoothing cannot substitute "
        "for a causal upstream information process with independently replicated "
        "positive economics and creates no correction or epoch-restart authority."
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
            "the exact long/cash transition-smoothing programme closure found zero "
            "supportive groups across seven completed mechanisms and only one of "
            "twelve closure gates passed"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Do not reopen the completed "
        "long/cash transition-smoothing programme through another hysteresis band, "
        "cooldown, persistence requirement, smoothing coefficient, cohort, delay or "
        "target subset. Freeze a materially orthogonal anonymous public source "
        "contract and falsifiable per-instrument temporal rule before feature or "
        "target-return access."
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
    assert window["prior_last_signal_bar_start"] == "2026-08-03T01:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T02:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T02:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T03:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 625
    assert window["updated_cumulative_realized_hours"] == 626

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-03T02:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    architecture = result["latest_training_only_architecture"]
    assert architecture["issue"] == 1016
    assert architecture["pull_request"] == 1018
    assert architecture["exact_tested_head"] == (
        "922bde13ceb8248184903053c4e4c64af6aa0279"
    )
    assert architecture["workflow_run"] == 30779885484
    assert architecture["artifact_id"] == 8843273000
    assert architecture["candidate_count"] == 0
    assert architecture["parameter_grid_count"] == 0
    assert architecture["bound_mechanism_groups"] == 7
    assert architecture["supportive_group_count"] == 0
    assert architecture["closure_gate_pass_count"] == 1
    assert architecture["closure_gate_total"] == 12
    assert architecture["performance_accessed"] is False
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
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T03:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 626
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
        "# Prospective simple-trend checkpoint through 03:00 UTC on 3 August 2026\n\n"
        "The 02:00 signal bar was provider-confirmed. The 03:00 candle supplied "
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
