from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_0500 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_726_000_000
REALIZED_DECISION_HOUR_MS = 1_785_729_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_729_600_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_733_200_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_715_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_736_800_000

PRIOR_RESULT_SHA256 = (
    "4a6cd94fa4f6e47844c0f6b1b5102f52e0f703a8e3168ba37a0d55bf6fef91cb"
)
PRIOR_ARTIFACT_SHA256 = (
    "4c2d2be135467961cd9bd0161b8479c10ddd2123775d4cab4a6f8aeabc60e1f1"
)
PRIOR_PULL_REQUEST = 1028
PRIOR_WORKFLOW_RUN = 30786812735
PRIOR_ARTIFACT_ID = 8845516305
PRIOR_CUMULATIVE_REALIZED_HOURS = 628
UPDATED_CUMULATIVE_REALIZED_HOURS = 629

LATEST_TRAINING_ARCHITECTURE: dict[str, Any] = {
    "family_id": (
        "causal-own-price-volume-directional-interaction-programme-closure-1h-v1"
    ),
    "issue": 1027,
    "pull_request": 1029,
    "exact_tested_head": "270f9951b1bd16f06227da768aad74b375552e85",
    "workflow_run": 30787837821,
    "artifact_id": 8845886112,
    "artifact_sha256": (
        "56180347933cf65ac63fc0bc7416f5b8ca1024cd8a156255cde396909b5b90f0"
    ),
    "evidence_sha256": (
        "88fe4559e5d73dcc3f41a93cef6250515c32f69cd758feb052084a0d12976583"
    ),
    "source_records_sha256": (
        "189ac90f0f980eea0d78ac6223da7a740a7a11199c2942860d92d6327cd704ea"
    ),
    "report_sha256": (
        "8ea748c50ec2fa3ec1eaee563bb8a21207c064e111d8607dc13cee2c5f040532"
    ),
    "bound_completed_mechanism_groups": 6,
    "historical_candidate_count": 8,
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "supportive_groups": 0,
    "closure_gates_passed": 3,
    "closure_gate_count": 12,
    "new_market_data_rows": 0,
    "new_target_labels": 0,
    "new_benchmark_values": 0,
    "new_bootstrap_draws": 0,
    "new_oos_access": False,
    "strategy_performance_accessed": False,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_completed_family",
    "verdict": (
        "reject_reopening_completed_own_price_volume_directional_interaction_"
        "mechanisms_1h_v1"
    ),
    "highest_value_failure": (
        "No completed directional price-volume interaction mechanism was "
        "independently admissible under its original bilateral source, absolute "
        "economics, benchmark, turnover-efficiency, drawdown, breadth, dependence "
        "and delay requirements. All six leave-one-group-out subsets and every "
        "mechanism-type subset retained zero admissible mechanisms."
    ),
    "strategy_facing_conclusion": (
        "Completed direct own-price/participation interactions are closed against "
        "same-family rescue and create no correction or observation-epoch restart "
        "authority."
    ),
}

ACTIVE_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-onchain-native-fee-pressure-source-contract-1h-v1",
    "issue": 1030,
    "status": "preregistered_source_contract_only",
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "provider": "Coin Metrics Community API",
    "source_metric": "FeeTotNtv",
    "source_frequency": "1h",
    "target_arms": ["BTC-USDT", "ETH-USDT"],
    "expected_rows_per_source_arm": 24_144,
    "target_returns_accessed": False,
    "strategy_performance_accessed": False,
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
        "LATEST_TRAINING_ARCHITECTURE": LATEST_TRAINING_ARCHITECTURE,
        "ACTIVE_ARCHITECTURE": ACTIVE_ARCHITECTURE,
    }
    for name, value in assignments.items():
        setattr(checkpoint, name, value)
    checkpoint.configure_checkpoint()


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
            "the completed directional price-volume interaction programme was "
            "terminally rejected and the active on-chain native fee-pressure work is "
            "a zero-candidate source contract that has not accessed target returns or "
            "created correction authority"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Execute issue #1030 only as its "
        "frozen bilateral source-contract audit: direct anonymous provider-native "
        "FeeTotNtv 1H data, no target-price access and no feature or sign selection. "
        "Do not reopen the completed own-price/volume directional-interaction family."
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
    assert window["prior_last_signal_bar_start"] == "2026-08-03T04:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T05:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T05:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T06:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 628
    assert window["updated_cumulative_realized_hours"] == 629

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-03T05:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    architecture = result["latest_training_only_architecture"]
    assert architecture["issue"] == 1027
    assert architecture["pull_request"] == 1029
    assert architecture["bound_completed_mechanism_groups"] == 6
    assert architecture["supportive_groups"] == 0
    assert architecture["closure_gates_passed"] == 3
    assert architecture["closure_gate_count"] == 12
    assert architecture["candidate_count"] == 0
    assert architecture["parameter_grid_count"] == 0
    assert architecture["strategy_performance_accessed"] is False
    assert architecture["sealed_oos_accessed"] is False
    assert architecture["correction_authority"] is False

    active = result["active_strategy_architecture"]
    assert active["issue"] == 1030
    assert active["candidate_count"] == 0
    assert active["parameter_grid_count"] == 0
    assert active["target_returns_accessed"] is False
    assert active["correction_authority"] is False

    correction = result["training_authorized_correction"]
    assert correction["permitted"] is False
    assert correction["applied"] is False
    assert correction["policy_changed"] is False
    assert correction["observation_epoch_restarted"] is False
    assert result["abort_conditions"]["triggered"] is False

    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T06:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 629
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
        "# Prospective simple-trend checkpoint through 06:00 UTC on 3 August 2026\n\n"
        "The 05:00 signal bar was provider-confirmed. The 06:00 candle supplied "
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
    result = checkpoint.checkpoint.call_inherited_checkpoint(
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
