from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_1600 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_679_200_000
REALIZED_DECISION_HOUR_MS = 1_785_682_800_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_682_800_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_686_400_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_668_400_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_690_000_000

PRIOR_RESULT_SHA256 = "ba84faee7d732c6cb1ed9b43495341f5837a0033263eeae9d1cf1917771135dc"
PRIOR_ARTIFACT_SHA256 = "ff9f140d307303ef213eb005a5931ffba9f0c70cd008193d9c523667dd31c63d"
PRIOR_PULL_REQUEST = 984
PRIOR_WORKFLOW_RUN = 30756354473
PRIOR_ARTIFACT_ID = 8836035350
PRIOR_CUMULATIVE_REALIZED_HOURS = 615
UPDATED_CUMULATIVE_REALIZED_HOURS = 616

LATEST_AUDIT = {
    "family_id": "causal-public-spot-borrow-demand-source-contract-1h-v1",
    "pull_request": 985,
    "exact_tested_head": "c7b70b0b6c709478f08d4c587104832c21fd2b06",
    "workflow_run": 30757218260,
    "artifact_id": 8836300632,
    "artifact_sha256": "731f6c06ff2a2ca536571b24016731f923d1f4ebd9a1f8247d870444b6f1cd6a",
    "source_arms_passing": 0,
    "source_arm_count": 2,
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "performance_accessed": False,
    "sealed_oos_accessed": False,
    "verdict": "reject_causal_public_spot_borrow_demand_source_contract_1h_v1",
    "correction_authority": False,
}


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


def patch_report(output_dir: Path) -> None:
    path = output_dir / "report.md"
    report = path.read_text()
    replacements = {
        "through 16:00 UTC on 2 August 2026": "through 17:00 UTC on 2 August 2026",
        "The 15:00 signal bar was provider-confirmed": (
            "The 16:00 signal bar was provider-confirmed"
        ),
        "The 16:00 candle supplied only its": (
            "The 17:00 candle supplied only its"
        ),
        "15:00–16:00 open-to-open payoff": "16:00–17:00 open-to-open payoff",
        (
            "The completed conditional-variance-state programme closure in PR #982 "
            "bound eight consumed own-price risk-state mechanism groups and found zero "
            "bilaterally supported groups, zero supportive leave-one-group-out subsets, "
            "candidate count zero and no correction authority. No active replacement "
            "architecture or newly frozen observation epoch exists."
        ): (
            "The public spot-borrow-demand source audit in PR #985 found that the "
            "provider's BTC and ETH borrowing-amount fields are deprecated and empty. "
            "Both source arms failed, candidate count remained zero, performance and "
            "sealed OOS were not accessed, and no correction authority was created. "
            "Borrowing rates were not substituted for borrowing-demand quantities."
        ),
        "- Closure family:": "- Latest audit family:",
        "- Closure verdict:": "- Latest audit verdict:",
    }
    for old, new in replacements.items():
        if old not in report:
            raise RuntimeError(f"report patch target missing: {old!r}")
        report = report.replace(old, new, 1)
    path.write_text(report)


def validate(result: dict[str, Any]) -> None:
    window = result["window"]
    assert result["policy_name"] == "simple_trend_long_cash_2160h_next_open"
    assert result["policy_sha256"] == (
        "9dc8ab03368b61546a6ae7674f1f4127953404900ff1e09e066ecf9adf741131"
    )
    assert result["bar"] == "1H"
    assert result["canonical_fee_bps_one_way"] == 5.0
    assert window["prior_last_signal_bar_start"] == "2026-08-02T15:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-02T16:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-02T16:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-02T17:00:00Z"
    assert window["updated_cumulative_realized_hours"] == 616
    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"]
        == "2026-08-02T16:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )
    assert result["training_authorized_correction"]["permitted"] is False
    assert result["training_authorized_correction"]["applied"] is False
    assert result["abort_conditions"]["triggered"] is False
    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-02T17:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["policy_changed"] is False
    assert machine["live_trading_authorized"] is False


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["window"]["prior_cumulative_realized_hours"] = (
        PRIOR_CUMULATIVE_REALIZED_HOURS
    )
    result["window"]["updated_cumulative_realized_hours"] = (
        UPDATED_CUMULATIVE_REALIZED_HOURS
    )
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
    result["latest_training_only_architecture"] = dict(LATEST_AUDIT)
    result["latest_source_audit"] = dict(LATEST_AUDIT)
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the latest orthogonal public spot-borrow-demand source contract failed "
            "bilaterally because provider-defined amount fields were deprecated and "
            "empty; candidate count remained zero and no active replacement exists"
        ),
    }
    result["next_strategy_action"] = (
        "advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation; do not substitute borrowing rates "
        "for the rejected spot-borrow-demand quantity source, and freeze any new "
        "materially orthogonal causal source contract and falsifiable temporal rule "
        "before feature or target-return access"
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
    machine["latest_training_diagnostic_verdict"] = LATEST_AUDIT["verdict"]

    validate(result)
    prior.write_result(output_dir, result)
    prior.write_report(output_dir, result)
    patch_report(output_dir)
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
