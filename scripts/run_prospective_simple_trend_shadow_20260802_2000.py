from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_1900 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_690_000_000
REALIZED_DECISION_HOUR_MS = 1_785_693_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_693_600_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_697_200_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_679_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_700_800_000

PRIOR_RESULT_SHA256 = (
    "55a58ef1ff871d8f54900435684ba513a818676c8b6c452224f9f4e4ea9de385"
)
PRIOR_ARTIFACT_SHA256 = (
    "9180801fabb00032f98fe1b47ac9fe3f6e1b8533a709c0ec3458432b222deb5d"
)
PRIOR_PULL_REQUEST = 994
PRIOR_WORKFLOW_RUN = 30763174041
PRIOR_ARTIFACT_ID = 8838093346
PRIOR_CUMULATIVE_REALIZED_HOURS = 618
UPDATED_CUMULATIVE_REALIZED_HOURS = 619

LATEST_SOURCE_AUDIT = {
    "family_id": "causal-public-spot-margin-lending-ratio-source-contract-1h-v1",
    "issue": 993,
    "pull_request": 995,
    "exact_tested_head": "9b10939649a0a511e9c207b64e94a94113cf0062",
    "workflow_run": 30763896329,
    "artifact_id": 8838313894,
    "artifact_sha256": (
        "1aa9da23b123c0ba5be82fae8ae5eb9e86180e3829bee6307f9b1fbf31c436cd"
    ),
    "source_arms_passing": 0,
    "source_arm_count": 2,
    "provider_code": "50030",
    "provider_message": "Illegal time range",
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "performance_accessed": False,
    "sealed_oos_accessed": False,
    "correction_authority": False,
    "status": "terminally_rejected_source_contract",
    "verdict": (
        "reject_causal_public_spot_margin_lending_ratio_source_contract_1h_v1"
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

    original_validate = checkpoint.validate
    original_persist = checkpoint.persist
    checkpoint.validate = lambda result: None
    checkpoint.persist = lambda output_dir, result: ""

    prior = checkpoint.checkpoint.prior
    lower_prior = prior.prior
    had_write_result = hasattr(prior, "write_result")
    had_write_report = hasattr(prior, "write_report")
    original_write_result = getattr(prior, "write_result", None)
    original_write_report = getattr(prior, "write_report", None)
    original_lower_write_report = lower_prior.write_report

    prior.write_result = lower_prior.write_result
    prior.write_report = lambda output_dir, result: None
    lower_prior.write_report = lambda output_dir, result: None
    try:
        return checkpoint.run(output_dir, base_url.rstrip("/"))
    finally:
        checkpoint.validate = original_validate
        checkpoint.persist = original_persist
        lower_prior.write_report = original_lower_write_report
        if had_write_result:
            prior.write_result = original_write_result
        else:
            delattr(prior, "write_result")
        if had_write_report:
            prior.write_report = original_write_report
        else:
            delattr(prior, "write_report")


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

    source_audit = dict(LATEST_SOURCE_AUDIT)
    result["active_alpha_context"] = source_audit
    result["latest_training_only_architecture"] = source_audit
    result["latest_source_audit"] = source_audit
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the sole preregistered margin-lending-ratio source contract was "
            "terminally rejected before full-panel acquisition or target-return "
            "access; candidate count and correction authority remain zero"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Open no replacement architecture "
        "until a materially orthogonal anonymous public source contract and a "
        "falsifiable per-instrument temporal rule are frozen before feature or "
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
    machine["latest_training_diagnostic_verdict"] = source_audit["verdict"]

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
    assert window["prior_last_signal_bar_start"] == "2026-08-02T18:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-02T19:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-02T19:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-02T20:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 618
    assert window["updated_cumulative_realized_hours"] == 619

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-02T19:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    audit = result["latest_source_audit"]
    assert audit["issue"] == 993
    assert audit["pull_request"] == 995
    assert audit["source_arms_passing"] == 0
    assert audit["candidate_count"] == 0
    assert audit["performance_accessed"] is False
    assert audit["sealed_oos_accessed"] is False
    assert audit["correction_authority"] is False

    correction = result["training_authorized_correction"]
    assert correction["permitted"] is False
    assert correction["applied"] is False
    assert correction["policy_changed"] is False
    assert correction["observation_epoch_restarted"] is False
    assert result["abort_conditions"]["triggered"] is False

    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-02T20:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 619
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
        "correction": result["training_authorized_correction"],
        "latest_source_audit": result["latest_source_audit"],
        "abort": result["abort_conditions"],
        "verdict": result["verdict"],
        "next_action": result["next_strategy_action"],
    }
    report = (
        "# Prospective simple-trend checkpoint through 20:00 UTC on 2 August 2026\n\n"
        "The 19:00 signal bar was provider-confirmed. The 20:00 candle supplied "
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
