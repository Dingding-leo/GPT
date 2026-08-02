from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_2200 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_700_800_000
REALIZED_DECISION_HOUR_MS = 1_785_704_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_704_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_708_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_690_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_711_600_000

PRIOR_RESULT_SHA256 = (
    "599564b7040f28ab0ceb791b9db64c5e781ec9698c0310285fdf16303d653175"
)
PRIOR_ARTIFACT_SHA256 = (
    "06d9b8c2e8bca7e803bda3dc17b5e39addd95a1126e31acf01a01c5ea009ee14"
)
PRIOR_PULL_REQUEST = 1003
PRIOR_WORKFLOW_RUN = 30769890112
PRIOR_ARTIFACT_ID = 8840154278
PRIOR_CUMULATIVE_REALIZED_HOURS = 621
UPDATED_CUMULATIVE_REALIZED_HOURS = 622

LATEST_TRAINING_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-public-insurance-fund-balance-source-contract-1h-v1",
    "issue": 1005,
    "pull_request": 1006,
    "exact_tested_head": "b231575a4d95131e55d2f91cb26dd2b90a9ec5bb",
    "workflow_run": 30771982858,
    "artifact_id": 8840803064,
    "artifact_sha256": (
        "1e9845021071f191cbccd84ca191f242cf92665e03edcea511bd0ede95b56105"
    ),
    "evidence_sha256": (
        "17e1d696bc95db2028c75261a82f8ee98f05bea21c05b778a28e5496041116fb"
    ),
    "report_sha256": (
        "f28b048f92b5e3beb1494d963d6ac16cb64755bfb17446d59609315426a92c3e"
    ),
    "source_arms_passing": 0,
    "source_arm_count": 2,
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "target_returns_accessed": False,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_source_contract",
    "verdict": "reject_causal_public_insurance_fund_balance_source_contract_1h_v1",
    "highest_value_failure": (
        "The anonymous provider history is settlement-driven daily data rather than "
        "provider-native hourly BTC and ETH balance panels. The frozen contract "
        "forbids reconstruction, resampling, provider stitching and field substitution."
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
            "the preregistered public insurance-fund balance source contract failed "
            "both provider-native hourly source arms before target-return access; "
            "candidate count and correction authority remained zero"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Do not reopen the rejected public "
        "insurance-fund balance source contract or reconstruct daily settlement data. "
        "Freeze a materially orthogonal anonymous public source contract and a "
        "falsifiable per-instrument temporal rule before feature or target-return access."
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
    assert window["prior_last_signal_bar_start"] == "2026-08-02T21:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-02T22:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-02T22:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-02T23:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 621
    assert window["updated_cumulative_realized_hours"] == 622

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-02T22:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    architecture = result["latest_training_only_architecture"]
    assert architecture["issue"] == 1005
    assert architecture["pull_request"] == 1006
    assert architecture["exact_tested_head"] == (
        "b231575a4d95131e55d2f91cb26dd2b90a9ec5bb"
    )
    assert architecture["workflow_run"] == 30771982858
    assert architecture["artifact_id"] == 8840803064
    assert architecture["source_arms_passing"] == 0
    assert architecture["source_arm_count"] == 2
    assert architecture["candidate_count"] == 0
    assert architecture["parameter_grid_count"] == 0
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
    assert machine["payoff_end_open_timestamp"] == "2026-08-02T23:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 622
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
        "# Prospective simple-trend checkpoint through 23:00 UTC on 2 August 2026\n\n"
        "The 22:00 signal bar was provider-confirmed. The 23:00 candle supplied "
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
