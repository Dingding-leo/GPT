from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_2300 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_704_400_000
REALIZED_DECISION_HOUR_MS = 1_785_708_000_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_708_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_711_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_693_600_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_715_200_000

PRIOR_RESULT_SHA256 = (
    "b21ba8c2132236ea05da88d65591d7fcf777900b810a5b2d0a5a4187798e52fb"
)
PRIOR_ARTIFACT_SHA256 = (
    "80447bf4b4687540aa885d5fd8bb6c0c21c3f2c377ee63c0520dd9d330c7649c"
)
PRIOR_PULL_REQUEST = 1007
PRIOR_WORKFLOW_RUN = 30772188357
PRIOR_ARTIFACT_ID = 8840870663
PRIOR_CUMULATIVE_REALIZED_HOURS = 622
UPDATED_CUMULATIVE_REALIZED_HOURS = 623

LATEST_TRAINING_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-own-price-e2160-noise-band-hysteresis-1h-v1",
    "issue": 1008,
    "pull_request": 1009,
    "exact_tested_head": "367efc3834d678e5c1e960085dbb94d2f995b993",
    "workflow_run": 30772706016,
    "artifact_id": 8841070461,
    "artifact_sha256": (
        "b5c0408ac7ab545f2e4371f67562543b9dd4d984f96a1e313f0cf98df08b7e4a"
    ),
    "evidence_sha256": (
        "a035b4a57a1048fc1686c6c8461678a56e3d69f2d064b31d08ba298d48db9099"
    ),
    "report_sha256": (
        "7e236464ffde0fcfe62fb81ac303acf80c328bbec7588b9035142124ce8305ca"
    ),
    "source_manifest_sha256": (
        "3a31338b005ba644b77a8e5e925d123f683635fecee2ddf615a3228ef84885bd"
    ),
    "candidate_count": 1,
    "parameter_grid_count": 0,
    "targets_passing": 0,
    "target_count": 2,
    "target_returns_accessed": True,
    "development_oos_accessed": True,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_candidate",
    "verdict": "reject_causal_own_price_e2160_noise_band_hysteresis_1h_v1",
    "highest_value_failure": (
        "The frozen adaptive E2160 noise band reduced turnover in both targets but "
        "lowered OOS and full-sample return and Sharpe, worsened drawdown, failed "
        "fold/year breadth and dependence gates, and remained inferior after one "
        "additional execution hour. Saved fees were smaller than foregone timing return."
    ),
    "strategy_facing_conclusion": (
        "State-level margin hysteresis is too coarse: it suppresses boundary churn "
        "but delays economically meaningful regime exits and re-entries."
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
            "the sole preregistered E2160 noise-band hysteresis candidate failed "
            "both targets' frozen economics, breadth, dependence and delayed-execution "
            "gates; its terminal rejection created no correction authority"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Do not rescue the rejected E2160 "
        "noise-band hysteresis family with another coefficient, window, quantile, "
        "asymmetric band, cooldown, smoothing or target subset. Freeze a materially "
        "orthogonal causal rule before feature or target-return access."
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
    assert window["prior_last_signal_bar_start"] == "2026-08-02T22:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-02T23:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-02T23:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T00:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 622
    assert window["updated_cumulative_realized_hours"] == 623

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-02T23:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    architecture = result["latest_training_only_architecture"]
    assert architecture["issue"] == 1008
    assert architecture["pull_request"] == 1009
    assert architecture["exact_tested_head"] == (
        "367efc3834d678e5c1e960085dbb94d2f995b993"
    )
    assert architecture["workflow_run"] == 30772706016
    assert architecture["artifact_id"] == 8841070461
    assert architecture["candidate_count"] == 1
    assert architecture["parameter_grid_count"] == 0
    assert architecture["targets_passing"] == 0
    assert architecture["target_count"] == 2
    assert architecture["target_returns_accessed"] is True
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
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T00:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 623
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
        "# Prospective simple-trend checkpoint through 00:00 UTC on 3 August 2026\n\n"
        "The 23:00 signal bar was provider-confirmed. The 00:00 candle supplied "
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
