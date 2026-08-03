from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import run_prospective_simple_trend_shadow_20260803_0600 as checkpoint
import run_public_onchain_activity_source_family_closure_20260803 as closure

PREVIOUS_DECISION_HOUR_MS = 1_785_729_600_000
REALIZED_DECISION_HOUR_MS = 1_785_733_200_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_733_200_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_736_800_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_718_800_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_740_400_000

PRIOR_RESULT_SHA256 = (
    "4dcc656baa22ee00e8db3cd4d8a172c4a5ad3a6cc770921141e0d7a5530ec1e5"
)
PRIOR_ARTIFACT_SHA256 = (
    "d9aa47f893f6d6dd244608d0d648c8243d36990c5b42ccf344d4389f59ca5095"
)
PRIOR_PULL_REQUEST = 1031
PRIOR_WORKFLOW_RUN = 30789962618
PRIOR_ARTIFACT_ID = 8846649282
PRIOR_CUMULATIVE_REALIZED_HOURS = 629
UPDATED_CUMULATIVE_REALIZED_HOURS = 630

CLOSURE_OUTPUT = (
    Path("reports/experiments")
    / "causal-public-onchain-activity-source-family-closure-1h-v2"
)


def iso_utc(hour_ms: int) -> str:
    return (
        datetime.fromtimestamp(hour_ms / 1000.0, tz=UTC)
        .isoformat()
        .replace("+00:00", "Z")
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_closure_evidence() -> tuple[dict[str, Any], str]:
    evidence_path = CLOSURE_OUTPUT / "evidence.json"
    if not evidence_path.exists():
        exact_head = os.environ.get("GITHUB_SHA", "")
        evidence = closure.build_evidence(exact_head)
        closure.validate(evidence)
        closure.persist(CLOSURE_OUTPUT, evidence)
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    closure.validate(evidence)
    return evidence, sha256_file(evidence_path)


def architecture_summary(evidence: dict[str, Any], evidence_sha: str) -> dict[str, Any]:
    return {
        "family_id": evidence["family_id"],
        "issue": 1033,
        "pull_request": None,
        "exact_tested_head": evidence["exact_head"],
        "evidence_sha256": evidence_sha,
        "bound_completed_mechanism_groups": evidence["architecture_group_count"],
        "supportive_groups": evidence["supportive_group_count"],
        "candidate_count": evidence["candidate_count"],
        "parameter_grid_count": evidence["parameter_grid_count"],
        "new_market_data_rows": evidence["new_market_data_rows"],
        "new_target_labels": evidence["new_target_returns"],
        "new_oos_access": bool(evidence["new_oos_consumed"]),
        "strategy_performance_accessed": False,
        "sealed_oos_accessed": False,
        "canonical_strategy_changed": evidence["canonical_strategy_changed"],
        "correction_authority": evidence["correction_authority"],
        "paper_trading_authorized": evidence["paper_trading_authorized"],
        "live_trading_authorized": evidence["live_trading_authorized"],
        "status": "terminally_rejected_completed_family",
        "verdict": evidence["verdict"],
        "highest_value_failure": evidence["highest_value_failure"],
        "closure_boundary": evidence["closure_boundary"],
        "economics": evidence["economics"],
    }


def no_active_architecture() -> dict[str, Any]:
    return {
        "family_id": None,
        "issue": None,
        "status": "no_active_replacement_architecture",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "target_returns_accessed": False,
        "strategy_performance_accessed": False,
        "sealed_oos_accessed": False,
        "correction_authority": False,
        "canonical_mutation_authorized": False,
        "paper_trading_authorized": False,
        "live_trading_authorized": False,
    }


def configure_checkpoint(
    latest_architecture: dict[str, Any], active_architecture: dict[str, Any]
) -> None:
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
        "LATEST_TRAINING_ARCHITECTURE": latest_architecture,
        "ACTIVE_ARCHITECTURE": active_architecture,
    }
    for name, value in assignments.items():
        setattr(checkpoint, name, value)
    checkpoint.configure_checkpoint()


def call_inherited_core(output_dir: Path, base_url: str) -> dict[str, Any]:
    module: ModuleType = checkpoint
    for _ in range(10):
        inherited = getattr(module, "call_inherited_checkpoint", None)
        if callable(inherited):
            return inherited(output_dir, base_url)
        nested = getattr(module, "checkpoint", None)
        if not isinstance(nested, ModuleType):
            break
        module = nested
    raise RuntimeError("inherited prospective strategy checkpoint is unavailable")


def finalize(
    result: dict[str, Any],
    latest_architecture: dict[str, Any],
    active_architecture: dict[str, Any],
) -> dict[str, Any]:
    result = checkpoint.finalize(result)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["active_alpha_context"] = dict(latest_architecture)
    result["latest_training_only_architecture"] = dict(latest_architecture)
    result["active_strategy_architecture"] = dict(active_architecture)
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the completed credential-free public on-chain activity family contains "
            "no bilateral executable provider-native 1H source contract, no target-"
            "return access and no correction authority"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Do not reopen Community TxCnt, "
        "FeeTotUSD or FeeTotNtv through aliases, unit substitutions, combinations, "
        "altered windows, lags, smoothing, signs, interpolation, shortened calendars "
        "or single-market promotion. Freeze a materially orthogonal direct public "
        "provider-native 1H information object and falsifiable per-instrument temporal "
        "rule before source or target-return access."
    )
    machine = result["machine_readable_verdict"]
    machine["updated_cumulative_realized_hours"] = UPDATED_CUMULATIVE_REALIZED_HOURS
    machine["payoff_end_open_timestamp"] = iso_utc(PAYOFF_END_OPEN_HOUR_MS)
    machine["correction_permitted"] = False
    machine["correction_applied"] = False
    machine["policy_changed"] = False
    machine["observation_epoch_restarted"] = False
    machine["latest_training_diagnostic_verdict"] = latest_architecture["verdict"]
    machine["active_family_id"] = None
    machine["active_family_status"] = active_architecture["status"]
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
    assert window["prior_last_signal_bar_start"] == "2026-08-03T05:00:00Z"
    assert window["latest_complete_signal_bar_start"] == "2026-08-03T06:00:00Z"
    assert window["realized_payoff_interval_start"] == "2026-08-03T06:00:00Z"
    assert window["realized_payoff_interval_end"] == "2026-08-03T07:00:00Z"
    assert window["new_signal_bar_count"] == 1
    assert window["new_realized_payoff_intervals"] == 1
    assert window["prior_cumulative_realized_hours"] == 629
    assert window["updated_cumulative_realized_hours"] == 630

    assert len(result["markets"]) == 2
    assert all(len(market["new_decisions"]) == 1 for market in result["markets"])
    assert all(
        market["new_decisions"][0]["signal_hour_start"] == "2026-08-03T06:00:00Z"
        for market in result["markets"]
    )
    assert all(
        source["grid"]["contiguous_confirmed_grid_passed"] is True
        for source in result["sources"]
    )

    architecture = result["latest_training_only_architecture"]
    assert architecture["issue"] == 1033
    assert architecture["bound_completed_mechanism_groups"] == 3
    assert architecture["supportive_groups"] == 0
    assert architecture["candidate_count"] == 0
    assert architecture["parameter_grid_count"] == 0
    assert architecture["strategy_performance_accessed"] is False
    assert architecture["sealed_oos_accessed"] is False
    assert architecture["correction_authority"] is False
    assert architecture["verdict"] == closure.VERDICT
    assert all(value is None for value in architecture["economics"].values())

    active = result["active_strategy_architecture"]
    assert active["family_id"] is None
    assert active["candidate_count"] == 0
    assert active["correction_authority"] is False

    correction = result["training_authorized_correction"]
    assert correction["permitted"] is False
    assert correction["applied"] is False
    assert correction["policy_changed"] is False
    assert correction["observation_epoch_restarted"] is False
    assert result["abort_conditions"]["triggered"] is False

    machine = result["machine_readable_verdict"]
    assert machine["payoff_end_open_only"] is True
    assert machine["payoff_end_open_timestamp"] == "2026-08-03T07:00:00Z"
    assert machine["future_signal_accessed"] is False
    assert machine["strategy_value_changed"] is False
    assert machine["updated_cumulative_realized_hours"] == 630
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
        "# Prospective simple-trend checkpoint through 07:00 UTC on 3 August 2026\n\n"
        "The 06:00 signal bar was provider-confirmed. The 07:00 candle supplied "
        "only its fixed opening price as the payoff endpoint.\n\n"
        "The completed credential-free public on-chain activity family was rejected "
        "from immutable prior evidence without new market rows, labels or OOS access.\n\n"
        "```json\n"
        + json.dumps(compact, sort_keys=True, indent=2, allow_nan=False)
        + "\n```\n\n"
        + f"Result SHA-256: `{digest}`\n"
    )
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    return digest


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    closure_evidence, closure_sha = load_closure_evidence()
    latest_architecture = architecture_summary(closure_evidence, closure_sha)
    active_architecture = no_active_architecture()
    configure_checkpoint(latest_architecture, active_architecture)
    result = call_inherited_core(output_dir, base_url.rstrip("/"))
    result = finalize(result, latest_architecture, active_architecture)
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
