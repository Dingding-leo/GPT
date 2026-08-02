from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_2200 as base

LATEST_TRAINING_ARCHITECTURE: dict[str, Any] = {
    "family_id": "causal-own-price-time-reversal-asymmetry-shift-opportunity-1h-v1",
    "pull_request": 1001,
    "exact_tested_head": "b3f367bbab96ebae133bac6f377af767b34d2467",
    "workflow_run": 30768339690,
    "artifact_id": 8839716975,
    "artifact_sha256": "61f514c89d5ceb9fe0af0b22f91eb9116302ff35db64673eff30e862e8242bad",
    "evidence_sha256": "359e470cdb2991039fb78256fbab926c2f05adbed9ccd3c640786346a589d2ec",
    "protocol_sha256": "ad8bf57c694d825a14a03c05c7f17ee6446d8ec16c7363b9973038c221356694",
    "source_manifest_sha256": "f8836d63200fea6ee521fc35e233abe8fac73ece3c28f0d7e4ed0aacc721e9a0",
    "source_contract_passed": True,
    "targets_passing": 0,
    "target_count": 2,
    "bilateral_training_support_passed": False,
    "candidate_count": 0,
    "parameter_grid_count": 0,
    "strategy_performance_accessed": False,
    "full_sample_accessed": False,
    "sealed_oos_accessed": False,
    "canonical_strategy_changed": False,
    "correction_authority": False,
    "paper_trading_authorized": False,
    "live_trading_authorized": False,
    "verdict": "reject_causal_own_price_time_reversal_asymmetry_shift_information_premise_1h_v1",
    "highest_value_failure": (
        "Both BTC-USDT and ETH-USDT failed the preregistered bilateral association, "
        "uncertainty, fold-breadth and one-hour-delay support gates; no executable "
        "candidate or separate candidate predeclaration was authorized."
    ),
}


def finalize_latest_architecture(result: dict[str, Any]) -> dict[str, Any]:
    architecture = dict(LATEST_TRAINING_ARCHITECTURE)
    result["active_alpha_context"] = architecture
    result["latest_training_only_architecture"] = architecture
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the latest preregistered own-price time-reversal-asymmetry shift "
            "information premise passed its source contract but failed both targets; "
            "candidate count and correction authority remained zero"
        ),
    }
    result["next_strategy_action"] = (
        "Advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation. Do not rescue the rejected "
        "time-reversal-asymmetry-shift family. Freeze a materially orthogonal "
        "anonymous public source contract and a falsifiable per-instrument temporal "
        "rule before feature or target-return access."
    )
    machine = result["machine_readable_verdict"]
    machine["correction_permitted"] = False
    machine["correction_applied"] = False
    machine["policy_changed"] = False
    machine["observation_epoch_restarted"] = False
    machine["active_family_id"] = None
    machine["active_family_status"] = "none"
    machine["latest_training_diagnostic_verdict"] = architecture["verdict"]
    return result


def validate(result: dict[str, Any]) -> None:
    base.validate(result)
    architecture = result["latest_training_only_architecture"]
    assert architecture["pull_request"] == 1001
    assert architecture["exact_tested_head"] == (
        "b3f367bbab96ebae133bac6f377af767b34d2467"
    )
    assert architecture["workflow_run"] == 30768339690
    assert architecture["artifact_id"] == 8839716975
    assert architecture["source_contract_passed"] is True
    assert architecture["targets_passing"] == 0
    assert architecture["target_count"] == 2
    assert architecture["bilateral_training_support_passed"] is False
    assert architecture["candidate_count"] == 0
    assert architecture["parameter_grid_count"] == 0
    assert architecture["strategy_performance_accessed"] is False
    assert architecture["full_sample_accessed"] is False
    assert architecture["sealed_oos_accessed"] is False
    assert architecture["canonical_strategy_changed"] is False
    assert architecture["correction_authority"] is False
    assert result["machine_readable_verdict"]["latest_training_diagnostic_verdict"] == (
        "reject_causal_own_price_time_reversal_asymmetry_shift_information_premise_1h_v1"
    )


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
        "# Prospective simple-trend checkpoint through 22:00 UTC on 2 August 2026\n\n"
        "The 21:00 signal bar was provider-confirmed. The 22:00 candle supplied "
        "only its fixed opening price as the payoff endpoint.\n\n"
        "```json\n"
        + json.dumps(compact, sort_keys=True, indent=2, allow_nan=False)
        + "\n```\n\n"
        + f"Result SHA-256: `{digest}`\n"
    )
    (output_dir / "report.md").write_text(report)
    return digest


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    result = base.run(output_dir, base_url)
    result = finalize_latest_architecture(result)
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
