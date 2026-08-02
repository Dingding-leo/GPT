from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_2000 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_693_600_000
REALIZED_DECISION_HOUR_MS = 1_785_697_200_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_697_200_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_700_800_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_682_800_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_704_400_000

PRIOR_RESULT_SHA256 = (
    "bde0f44107c631f28c19d6184324851d3dfaf2a752da8ba8f6dca23144e143fe"
)
PRIOR_ARTIFACT_SHA256 = (
    "38d5bbea120d44f8e6cf47be26d0454fa358cc03bafd1a280643f3f00f1bb37a"
)
PRIOR_PULL_REQUEST = 997
PRIOR_WORKFLOW_RUN = 30765274074
PRIOR_ARTIFACT_ID = 8838722004
PRIOR_CUMULATIVE_REALIZED_HOURS = 619
UPDATED_CUMULATIVE_REALIZED_HOURS = 620

LATEST_PROGRAMME_CLOSURE = {
    "family_id": (
        "causal-public-spot-margin-balance-sheet-crowding-programme-closure-1h-v1"
    ),
    "issue": 996,
    "pull_request": 998,
    "exact_tested_head": "cfff75fad3e30fa5b0b67acc7f205c14420192ec",
    "workflow_run": 30766146229,
    "artifact_id": 8838995169,
    "artifact_sha256": (
        "e5685d197e856d08b51cd033aac97f197633976a8efd7ea6d0a9b33f48539f62"
    ),
    "evidence_sha256": (
        "8ac82a6a61ffe7ccf9cbf2d53e2ea1f719572874a8cc94ce8ded48d78900e4ab"
    ),
    "bound_mechanism_groups": 3,
    "admissible_bilateral_mechanisms": 0,
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "new_market_rows": 0,
    "new_target_rows": 0,
    "new_oos_rows": 0,
    "performance_accessed": False,
    "sealed_oos_accessed": False,
    "correction_authority": False,
    "status": "terminally_rejected_programme_closure",
    "verdict": (
        "reject_reopening_completed_public_spot_margin_balance_sheet_"
        "crowding_mechanisms_1h_v1"
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

    closure = dict(LATEST_PROGRAMME_CLOSURE)
    result["active_alpha_context"] = closure
    result["latest_training_only_architecture"] = closure
    result["latest_programme_closure"] = closure
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the completed public spot-margin balance-sheet crowding programme "
            "contains zero admissible bilateral mechanisms and created no "
            "candidate or correction authority"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Do not reopen the completed "
        "public spot-margin balance-sheet crowding mechanisms. Freeze a materially "
        "orthogonal anonymous public source contract and a falsifiable "
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
    machine["latest_training_diagnostic_verdict"] = closure["verdict"]

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
    assert window["prior_last_signal_bar_start"] == "2026-08-02T19:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-02T20:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-02T20:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-02T21:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 619
    assert window["updated_cumulative_realized_hours"] == 620

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-02T20:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    closure = result["latest_programme_closure"]
    assert closure["issue"] == 996
    assert closure["pull_request"] == 998
    assert closure["bound_mechanism_groups"] == 3
    assert closure["admissible_bilateral_mechanisms"] == 0
    assert closure["candidate_count"] == 0
    assert closure["performance_accessed"] is False
    assert closure["sealed_oos_accessed"] is False
    assert closure["correction_authority"] is False

    correction = result["training_authorized_correction"]
    assert correction["permitted"] is False
    assert correction["applied"] is False
    assert correction["policy_changed"] is False
    assert correction["observation_epoch_restarted"] is False
    assert result["abort_conditions"]["triggered"] is False

    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-02T21:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 620
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
        "latest_programme_closure": result["latest_programme_closure"],
        "abort": result["abort_conditions"],
        "verdict": result["verdict"],
        "next_action": result["next_strategy_action"],
    }
    report = (
        "# Prospective simple-trend checkpoint through 21:00 UTC on 2 August 2026\n\n"
        "The 20:00 signal bar was provider-confirmed. The 21:00 candle supplied "
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
