from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_0400 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_722_400_000
REALIZED_DECISION_HOUR_MS = 1_785_726_000_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_726_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_729_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_711_600_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_733_200_000

PRIOR_RESULT_SHA256 = (
    "8d061ace1d88503712f3ef7dd0a43104e6ca6336b5b38defafad4b47ad246d76"
)
PRIOR_ARTIFACT_SHA256 = (
    "c57def5f9c337944721fea4c13e0081db0e0e53bc3cee82c76abc5a9d42ae296"
)
PRIOR_PULL_REQUEST = 1024
PRIOR_WORKFLOW_RUN = 30783929961
PRIOR_ARTIFACT_ID = 8844585544
PRIOR_CUMULATIVE_REALIZED_HOURS = 627
UPDATED_CUMULATIVE_REALIZED_HOURS = 628

LATEST_TRAINING_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-own-price-volume-lead-lag-asymmetry-opportunity-1h-v1",
    "issue": 1025,
    "pull_request": 1026,
    "exact_tested_head": "6215c7e012898e22cd7f723ea7f549ae45aad1a3",
    "workflow_run": 30784852184,
    "artifact_id": 8844992170,
    "artifact_sha256": (
        "2b101bd58afbf4e23567107ad9bc76628adbba08160333fc61857e0c0af0e83f"
    ),
    "evidence_sha256": (
        "94fe3baf057b353fe588fd337ae3e03129ebe55dea782e2466346e089020ae0f"
    ),
    "report_sha256": (
        "dc4410318520480735dc6d8b95fb34518d8325c317390e535e189b7fcfcf1781"
    ),
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "source_arm_count": 2,
    "source_arms_passing": 2,
    "targets_passing": 0,
    "target_count": 2,
    "rows_per_target": 24_144,
    "targets": {
        "LTC-USDT": {
            "opportunity_count": 205,
            "net_spearman": -0.055694,
            "adverse_spearman": 0.066512,
            "net_standardized_slope": -0.047091,
            "adverse_standardized_slope": 0.052478,
            "net_upper_minus_lower_bps": -27.08,
            "adverse_upper_minus_lower_bps": 32.42,
            "positive_net_slope_folds": 2,
            "fold_count": 4,
            "delayed_net_spearman": -0.058399,
            "delayed_net_upper_minus_lower_bps": -18.32,
        },
        "DOGE-USDT": {
            "opportunity_count": 223,
            "net_spearman": -0.033687,
            "adverse_spearman": 0.054906,
            "net_standardized_slope": -0.083340,
            "adverse_standardized_slope": 0.092666,
            "net_upper_minus_lower_bps": -55.82,
            "adverse_upper_minus_lower_bps": 51.49,
            "positive_net_slope_folds": 1,
            "fold_count": 4,
            "delayed_net_spearman": -0.039511,
            "delayed_net_upper_minus_lower_bps": -78.15,
        },
    },
    "all_required_dependence_lower_bounds_positive": False,
    "strategy_performance_accessed": False,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_information_premise",
    "verdict": (
        "reject_causal_own_price_volume_lead_lag_asymmetry_information_premise_1h_v1"
    ),
    "highest_value_failure": (
        "The public source and exact time-direction semantics passed bilaterally, but "
        "higher recent volume-leading-price asymmetry predicted lower fee-adjusted "
        "next-24H continuation in both LTC and DOGE. All eight required dependence "
        "lower bounds were negative, net fold breadth failed, and the negative net "
        "association persisted after a one-hour execution delay."
    ),
    "strategy_facing_conclusion": (
        "The tested price-volume temporal-ordering statistic cannot support an "
        "unlevered per-instrument long/cash correction and creates no observation-epoch "
        "restart authority."
    ),
}

ACTIVE_ARCHITECTURE: dict[str, Any] = {
    "family_id": (
        "causal-own-price-volume-directional-interaction-programme-closure-1h-v1"
    ),
    "issue": 1027,
    "status": "preregistered_zero_candidate_evidence_closure",
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "bound_completed_mechanism_groups": 6,
    "new_market_data_rows": 0,
    "new_target_labels": 0,
    "new_oos_access": False,
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
            "the latest frozen price-volume lead-lag information premise failed "
            "bilaterally and issue 1027 is a zero-candidate completed-family evidence "
            "closure with no correction authority"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Complete issue #1027 exclusively "
        "from immutable prior evidence; do not rescue the rejected price-volume "
        "lead-lag premise through another sign, lag, window, volume field, cohort, "
        "threshold or fitted combination. Freeze a materially orthogonal causal source "
        "contract and per-instrument temporal rule before new feature or target access."
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
    assert window["prior_last_signal_bar_start"] == "2026-08-03T03:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T04:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T04:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T05:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 627
    assert window["updated_cumulative_realized_hours"] == 628

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-03T04:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    architecture = result["latest_training_only_architecture"]
    assert architecture["issue"] == 1025
    assert architecture["pull_request"] == 1026
    assert architecture["source_arms_passing"] == 2
    assert architecture["targets_passing"] == 0
    assert architecture["candidate_count"] == 0
    assert architecture["parameter_grid_count"] == 0
    assert architecture["strategy_performance_accessed"] is False
    assert architecture["sealed_oos_accessed"] is False
    assert architecture["correction_authority"] is False

    active = result["active_strategy_architecture"]
    assert active["issue"] == 1027
    assert active["candidate_count"] == 0
    assert active["new_market_data_rows"] == 0
    assert active["correction_authority"] is False

    correction = result["training_authorized_correction"]
    assert correction["permitted"] is False
    assert correction["applied"] is False
    assert correction["policy_changed"] is False
    assert correction["observation_epoch_restarted"] is False
    assert result["abort_conditions"]["triggered"] is False

    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T05:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 628
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
        "# Prospective simple-trend checkpoint through 05:00 UTC on 3 August 2026\n\n"
        "The 04:00 signal bar was provider-confirmed. The 05:00 candle supplied "
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
