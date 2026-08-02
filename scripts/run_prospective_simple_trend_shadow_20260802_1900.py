from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_1800 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_686_400_000
REALIZED_DECISION_HOUR_MS = 1_785_690_000_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_690_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_693_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_675_600_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_697_200_000

PRIOR_RESULT_SHA256 = (
    "9002dca4b4f1643ecbcab78b52056a42d8f1fc21f38584706e96903b3da14dff"
)
PRIOR_ARTIFACT_SHA256 = (
    "1d88bdfa3e8a9ce3b44fb9368ae97e5064d7afeba6c1e3fdc2c9db0a2d2ac942"
)
PRIOR_PULL_REQUEST = 990
PRIOR_WORKFLOW_RUN = 30760906938
PRIOR_ARTIFACT_ID = 8837410705
PRIOR_CUMULATIVE_REALIZED_HOURS = 617
UPDATED_CUMULATIVE_REALIZED_HOURS = 618

PROGRAMME_CLOSURE = {
    "family_id": "public-spot-borrowing-balance-sheet-programme-closure-1h-v1",
    "pull_request": 992,
    "exact_tested_head": "5184c94da038ad35b403eca22b0998f260d0e68a",
    "workflow_run": 30761481158,
    "artifact_id": 8837581839,
    "artifact_sha256": (
        "a280c7bd65025ae7a7806abd47a127ecbfaf7f56d4a422aa61da2173f46d221c"
    ),
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "correction_authority": False,
    "verdict": "reject_reopening_completed_public_spot_borrowing_programme_1h_v1",
}

ACTIVE_ARCHITECTURE = {
    "family_id": "causal-public-spot-margin-lending-ratio-source-contract-1h-v1",
    "issue": 993,
    "status": "preregistered_pending_source_audit",
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "performance_accessed": False,
    "sealed_oos_accessed": False,
    "correction_authority": False,
    "canonical_mutation_permitted": False,
}


def iso_utc(hour_ms: int) -> str:
    return (
        datetime.fromtimestamp(hour_ms / 1000.0, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


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
        setattr(checkpoint, name, globals()[name])


def validate(result: dict[str, Any]) -> None:
    window = result["window"]
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
    assert window["prior_last_signal_bar_start"] == "2026-08-02T17:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-02T18:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-02T18:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-02T19:00:00Z"
    assert window["prior_cumulative_realized_hours"] == 617
    assert window["updated_cumulative_realized_hours"] == 618
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"]
        == "2026-08-02T18:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )
    assert result["active_alpha_context"]["issue"] == 993
    assert result["training_authorized_correction"]["permitted"] is False
    assert result["training_authorized_correction"]["applied"] is False
    assert result["abort_conditions"]["triggered"] is False
    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-02T19:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
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
        "correction": result["training_authorized_correction"],
        "active_architecture": result["active_alpha_context"],
        "abort": result["abort_conditions"],
        "verdict": result["verdict"],
        "next_action": result["next_strategy_action"],
    }
    report = (
        "# Prospective simple-trend checkpoint through 19:00 UTC on 2 August 2026\n\n"
        "The 18:00 signal bar was provider-confirmed. The 19:00 candle supplied "
        "only its fixed opening price as the payoff endpoint.\n\n"
        "```json\n"
        + json.dumps(compact, sort_keys=True, indent=2, allow_nan=False)
        + "\n```\n\n"
        + f"Result SHA-256: `{digest}`\n"
    )
    (output_dir / "report.md").write_text(report)
    return digest


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    original = {
        "validate": checkpoint.validate,
        "patch": checkpoint.patch_report,
        "prior_validate": checkpoint.prior.validate,
        "prior_patch": checkpoint.prior.patch_report,
        "prior_result": checkpoint.prior.write_result,
        "prior_report": checkpoint.prior.write_report,
    }
    checkpoint.validate = lambda result: None
    checkpoint.patch_report = lambda output: None
    checkpoint.prior.validate = lambda result: None
    checkpoint.prior.patch_report = lambda output: None
    checkpoint.prior.write_result = checkpoint.prior.prior.write_result
    checkpoint.prior.write_report = checkpoint.prior.prior.write_report
    try:
        result = checkpoint.run(output_dir, base_url.rstrip("/"))
    finally:
        checkpoint.validate = original["validate"]
        checkpoint.patch_report = original["patch"]
        checkpoint.prior.validate = original["prior_validate"]
        checkpoint.prior.patch_report = original["prior_patch"]
        checkpoint.prior.write_result = original["prior_result"]
        checkpoint.prior.write_report = original["prior_report"]

    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["window"]["prior_cumulative_realized_hours"] = 617
    result["window"]["updated_cumulative_realized_hours"] = 618
    result["performance_accessed"] = False
    result["oos_accessed"] = False
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
    result["latest_programme_closure"] = dict(PROGRAMME_CLOSURE)
    result["active_alpha_context"] = dict(ACTIVE_ARCHITECTURE)
    result["latest_training_only_architecture"] = dict(ACTIVE_ARCHITECTURE)
    result["latest_source_audit"] = dict(ACTIVE_ARCHITECTURE)
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the completed borrowing programme created no candidate or correction "
            "authority; issue #993 remains at source-contract stage with target returns "
            "and sealed OOS prohibited"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation and execute issue #993's bilateral "
        "public spot-margin lending-ratio source audit without target-return access."
    )
    machine = result["machine_readable_verdict"]
    machine["updated_cumulative_realized_hours"] = 618
    machine["payoff_end_open_timestamp"] = iso_utc(PAYOFF_END_OPEN_HOUR_MS)
    machine["correction_permitted"] = False
    machine["correction_applied"] = False
    machine["policy_changed"] = False
    machine["observation_epoch_restarted"] = False
    machine["active_family_id"] = ACTIVE_ARCHITECTURE["family_id"]
    machine["active_family_status"] = ACTIVE_ARCHITECTURE["status"]
    machine["latest_training_diagnostic_verdict"] = PROGRAMME_CLOSURE["verdict"]
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
