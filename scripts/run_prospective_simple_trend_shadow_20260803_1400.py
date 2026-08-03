from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260803_1300 as checkpoint

PREVIOUS_DECISION_HOUR_MS = 1_785_754_800_000
REALIZED_DECISION_HOUR_MS = 1_785_758_400_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_758_400_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_762_000_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_744_000_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_765_600_000

PRIOR_RESULT_SHA256 = (
    "5932e5895bf5043a91341cd7ed148d587d1642329914b0527efb12e6eda7a6dd"
)
PRIOR_ARTIFACT_SHA256 = (
    "631ba713889953d77f1d66c2ebc14f5763f2387f124e6e74e2b2fcfd44ae2d02"
)
PRIOR_PULL_REQUEST = 1058
PRIOR_WORKFLOW_RUN = 30817796676
PRIOR_ARTIFACT_ID = 8857476988
PRIOR_CUMULATIVE_REALIZED_HOURS = 636
UPDATED_CUMULATIVE_REALIZED_HOURS = 637

LATEST_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-own-price-linear-supervised-selector-programme-closure-1h-v1",
    "issue": 1060,
    "pull_request": 1061,
    "exact_head": "c352ccbad6cdae3f2fc0e50e3120dfdb3628ba0e",
    "workflow_run": 30821451563,
    "artifact_id": 8858995950,
    "artifact_sha256": (
        "742e4cdb0c67550e4028a46861c48b8223b62ef1d2732ac6e2a3b5409b869e99"
    ),
    "evidence_sha256": (
        "68fc085424b1ebe088715746a73c49c2da25bbab879421c7b5828178c44759fa"
    ),
    "report_sha256": (
        "8b1e189a2a482728ef304b8dba6cfe178045742878cd788ec1ce9b31c5fa51b4"
    ),
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "bound_evidence_units": 2,
    "independently_supportive_units": 0,
    "closure_gates_passed": 1,
    "closure_gates_total": 12,
    "fixed_targets": ["ETC-USDT", "FIL-USDT"],
    "new_market_rows_accessed": 0,
    "new_target_returns_accessed": 0,
    "target_returns_accessed": False,
    "strategy_performance_accessed": False,
    "benchmark_path_accessed": False,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "status": "terminally_rejected_programme_closure",
    "verdict": (
        "reject_reopening_completed_fixed_linear_supervised_selector_mechanisms_1h_v1"
    ),
    "highest_value_failure": (
        "The fixed ridge lag-strip exception reversed from large fit gains to "
        "bilateral validation losses, had insufficient fit support, suppressed "
        "profitable E2160 exposure and amplified turnover; OOS remained sealed."
    ),
    "next_action": (
        "Do not reopen fixed linear own-history selectors through alternate "
        "penalties, lag strips, thresholds, support rules, targets or refits."
    ),
}

ACTIVE_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-own-price-mixture-e-process-trend-evidence-selector-1h-v1",
    "issue": 1062,
    "status": "preregistered_not_evaluated",
    "fixed_targets": ["XRP-USDT", "ADA-USDT"],
    "candidate_count": 1,
    "parameter_grid_count": 0,
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


def inherited_core() -> Any:
    return checkpoint.inherited_core()


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
            "Issue 1060 terminally rejected the completed fixed linear supervised "
            "selector family. Issue 1062 is preregistered but unevaluated. Neither "
            "creates correction authority."
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow "
        "at the next complete public 1H observation. Evaluate issue 1062 only "
        "under its frozen XRP-USDT/ADA-USDT mixture e-process protocol. Keep OOS "
        "sealed unless both validation arms pass, and do not alter targets, source, "
        "mixture lambdas or weights, utility scale, evidence threshold, support "
        "floor, cadence, trend horizon, segments, comparators, bootstrap, delay, "
        "fee or acceptance gates after access."
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
    assert window["prior_last_signal_bar_start"] == "2026-08-03T12:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T13:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T13:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T14:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 636
    assert window["updated_cumulative_realized_hours"] == 637

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"]
        == "2026-08-03T13:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    latest = result["latest_training_only_architecture"]
    assert latest["issue"] == 1060
    assert latest["candidate_count"] == 0
    assert latest["parameter_grid_count"] == 0
    assert latest["sealed_oos_accessed"] is False
    assert latest["correction_authority"] is False
    assert latest["independently_supportive_units"] == 0

    active = result["active_strategy_architecture"]
    assert active["issue"] == 1062
    assert active["status"] == "preregistered_not_evaluated"
    assert active["candidate_count"] == 1
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
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T14:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 637
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
        "# Prospective simple-trend checkpoint through 14:00 UTC on "
        "3 August 2026\n\n"
        "The 13:00 signal bar was provider-confirmed. The 14:00 candle supplied "
        "only its fixed opening price as the payoff endpoint.\n\n"
        "The completed fixed linear supervised-selector programme is terminally "
        "closed with zero independently supportive evidence units. The XRP/ADA "
        "mixture e-process architecture in issue 1062 remains preregistered but "
        "unevaluated and cannot authorise a correction.\n\n"
        "```json\n"
        + json.dumps(compact, sort_keys=True, indent=2, allow_nan=False)
        + "\n```\n\n"
        + f"Result SHA-256: `{digest}`\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return digest


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_checkpoint()
    result = inherited_core()(output_dir, base_url.rstrip("/"))
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
