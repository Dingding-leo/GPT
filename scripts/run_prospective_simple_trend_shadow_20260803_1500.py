from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_1400 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_758_400_000
REALIZED_DECISION_HOUR_MS = 1_785_762_000_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_762_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_765_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_747_600_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_769_200_000

PRIOR_RESULT_SHA256 = (
    "c80e4abd0f612efbc7bb2eec96724f62c8772506e60ae2273b8bbe9e021ac157"
)
PRIOR_ARTIFACT_SHA256 = (
    "838bd8c7112516152c3724cc5f9b736703b6206718a5e99b1fe2ff06fe5b676f"
)
PRIOR_PULL_REQUEST = 1064
PRIOR_WORKFLOW_RUN = 30822393612
PRIOR_ARTIFACT_ID = 8859376622
PRIOR_CUMULATIVE_REALIZED_HOURS = 637
UPDATED_CUMULATIVE_REALIZED_HOURS = 638

LATEST_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-own-price-mixture-e-process-trend-evidence-selector-1h-v1",
    "issue": 1062,
    "pull_request": 1065,
    "exact_head": "b513bd3bcf3c2a3671baf1c54b0feed742d661f3",
    "workflow_run": 30824266694,
    "artifact_id": 8860261765,
    "artifact_sha256": (
        "3c66b374e2a45b014da484f988bea7c9c6bf070719ee8f6d6535de5d835f0601"
    ),
    "evidence_sha256": (
        "8a2b15e86f8835c0c71628327a22af5cb04909393836457b480c48af58028043"
    ),
    "report_sha256": (
        "c9fd9a1d514b57e72579eef9711198639b46f37e023970e022d142098478d5d1"
    ),
    "candidate_count": 1,
    "parameter_grid_count": 0,
    "fixed_targets": ["XRP-USDT", "ADA-USDT"],
    "validation_anchors_per_target": 274,
    "candidate_long_anchors": {"XRP-USDT": 0, "ADA-USDT": 0},
    "max_log_evidence": {"XRP-USDT": -3.194748, "ADA-USDT": -0.109972},
    "evidence_threshold_log": 2.995732,
    "validation_candidate_net_return": {"XRP-USDT": 0.0, "ADA-USDT": 0.0},
    "validation_candidate_sharpe": {"XRP-USDT": 0.0, "ADA-USDT": 0.0},
    "suppressed_e2160_mean_fee_clearing_return": {
        "XRP-USDT": 0.007071,
        "ADA-USDT": 0.008230,
    },
    "source_contract_passed": True,
    "bilateral_source_contract_passed": True,
    "bilateral_pass": False,
    "target_returns_accessed": True,
    "strategy_performance_accessed": True,
    "benchmark_path_accessed": False,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_before_sealed_oos",
    "verdict": (
        "reject_causal_own_price_mixture_e_process_trend_evidence_selector_1h_v1"
    ),
    "highest_value_failure": (
        "The fixed positive-utility mixture evidence process never reached its "
        "predeclared threshold in either validation arm and suppressed every "
        "positive-E2160 opportunity despite positive average fee-clearing returns."
    ),
    "next_action": (
        "Do not rescue the rejected payoff-evidence selector through alternate "
        "lambdas, weights, thresholds, utility scales, support floors, resets, "
        "markets, segment boundaries, target pooling or fee changes."
    ),
}

ACTIVE_ARCHITECTURE: dict[str, Any] = {
    "family_id": (
        "causal-own-price-return-sign-mixture-eprocess-shift-opportunity-1h-v1"
    ),
    "issue": 1063,
    "pull_request": 1066,
    "status": "preregistered_training_only_evaluation_in_progress",
    "fixed_targets": ["XLM-USDT", "ICP-USDT"],
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "source_access_attempted": True,
    "target_returns_accessed": False,
    "strategy_performance_accessed": False,
    "benchmark_path_accessed": False,
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
    }
    for name, value in assignments.items():
        setattr(checkpoint, name, value)
    checkpoint.LATEST_ARCHITECTURE = LATEST_ARCHITECTURE
    checkpoint.ACTIVE_ARCHITECTURE = ACTIVE_ARCHITECTURE
    checkpoint.configure_checkpoint()


def finalize(result: dict[str, Any]) -> dict[str, Any]:
    result = checkpoint.finalize(result)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["active_alpha_context"] = dict(LATEST_ARCHITECTURE)
    result["latest_training_only_architecture"] = dict(LATEST_ARCHITECTURE)
    result["active_strategy_architecture"] = dict(ACTIVE_ARCHITECTURE)
    result["evidence_wrapper_repair"] = {
        "applied": False,
        "strategy_value_changed": False,
        "source_changed": False,
        "fee_changed": False,
        "architecture_changed": False,
        "chronology_boundary_changed": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "Issue 1062 terminally rejected the fixed XRP/ADA mixture e-process "
            "selector before sealed OOS. Issue 1063 remains a zero-candidate, "
            "training-only information diagnostic. Neither creates correction authority."
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow "
        "at the next complete public 1H observation. Complete issue 1063 only "
        "under its frozen XLM-USDT/ICP-USDT return-sign mixture-e-process shift "
        "protocol. Repair only source-pagination correctness, not any target, "
        "fraction, window, lag, sign, fee, label, bootstrap, fold or gate value."
    )
    machine = result["machine_readable_verdict"]
    machine.update(
        {
            "updated_cumulative_realized_hours": UPDATED_CUMULATIVE_REALIZED_HOURS,
            "payoff_end_open_timestamp": iso_utc(PAYOFF_END_OPEN_HOUR_MS),
            "correction_permitted": False,
            "correction_applied": False,
            "policy_changed": False,
            "observation_epoch_restarted": False,
            "latest_training_diagnostic_verdict": LATEST_ARCHITECTURE["verdict"],
            "active_family_id": ACTIVE_ARCHITECTURE["family_id"],
            "active_family_status": ACTIVE_ARCHITECTURE["status"],
            "paper_trading_authorized": False,
            "live_trading_authorized": False,
        }
    )
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

    window = result["window"]
    assert window["prior_last_signal_bar_start"] == "2026-08-03T13:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T14:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T14:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T15:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 637
    assert window["updated_cumulative_realized_hours"] == 638

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"]
        == "2026-08-03T14:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    latest = result["latest_training_only_architecture"]
    assert latest["issue"] == 1062
    assert latest["candidate_count"] == 1
    assert latest["parameter_grid_count"] == 0
    assert latest["bilateral_pass"] is False
    assert latest["sealed_oos_accessed"] is False
    assert latest["correction_authority"] is False

    active = result["active_strategy_architecture"]
    assert active["issue"] == 1063
    assert active["candidate_count"] == 0
    assert active["parameter_grid_count"] == 0
    assert active["target_returns_accessed"] is False
    assert active["sealed_oos_accessed"] is False
    assert active["correction_authority"] is False

    correction = result["training_authorized_correction"]
    assert correction["permitted"] is False
    assert correction["applied"] is False
    assert correction["policy_changed"] is False
    assert correction["observation_epoch_restarted"] is False
    assert result["abort_conditions"]["triggered"] is False

    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T15:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 638
    assert machine["correction_permitted"] is False
    assert machine["live_trading_authorized"] is False


def persist(output_dir: Path, result: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    (output_dir / "result.json").write_text(payload, encoding="utf-8")
    (output_dir / "result.sha256").write_text(digest + "\n", encoding="utf-8")
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
        "# Prospective simple-trend checkpoint through 15:00 UTC on "
        "3 August 2026\n\n"
        "The 14:00 signal bar was provider-confirmed. The 15:00 candle supplied "
        "only its fixed opening price as the payoff endpoint.\n\n"
        "The XRP/ADA fixed mixture e-process selector is terminally rejected "
        "before sealed OOS. The XLM/ICP return-sign mixture-e-process shift in "
        "issue 1063 remains a zero-candidate training-only diagnostic and cannot "
        "authorise a correction.\n\n"
        "```json\n"
        + json.dumps(compact, sort_keys=True, indent=2, allow_nan=False)
        + "\n```\n\n"
        + f"Result SHA-256: `{digest}`\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return digest


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_checkpoint()
    result = checkpoint.inherited_core()(output_dir, base_url.rstrip("/"))
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
