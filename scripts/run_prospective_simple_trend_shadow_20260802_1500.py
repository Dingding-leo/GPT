from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_1400 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_672_000_000
REALIZED_DECISION_HOUR_MS = 1_785_675_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_675_600_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_679_200_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_661_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_682_800_000

PRIOR_RESULT_SHA256 = "3c3615302cf2fd41e50a9c8d35ece50278240020ed544eddbd257b21936c6cd3"
PRIOR_ARTIFACT_SHA256 = "00bf45e79230d7c00c34582c75533100a8a205433a59fe136942d9dccb470762"
PRIOR_PULL_REQUEST = 978
PRIOR_WORKFLOW_RUN = 30751705737
PRIOR_ARTIFACT_ID = 8834646720
PRIOR_CUMULATIVE_REALIZED_HOURS = 613
UPDATED_CUMULATIVE_REALIZED_HOURS = 614


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
        "through 14:00 UTC on 2 August 2026": "through 15:00 UTC on 2 August 2026",
        "The 13:00 signal bar was provider-confirmed": "The 14:00 signal bar was provider-confirmed",
        "The 14:00 candle supplied only its already-fixed open": "The 15:00 candle supplied only its already-fixed open",
        "13:00–14:00 open-to-open payoff": "14:00–15:00 open-to-open payoff",
        (
            "The latest additional training-only leverage-effect-relaxation architecture\n"
            "in PR #976 was rejected with targets passing 0/2, candidate count zero,\n"
            "parameter grid zero, sealed OOS unaccessed and no executable authority. No\n"
            "active replacement strategy architecture, training-authorised correction or\n"
            "replacement observation epoch exists."
        ): (
            "The latest additional training-only volatility-clustering-relaxation\n"
            "architecture in PR #979 was rejected with targets passing 0/2, candidate\n"
            "count zero, parameter grid zero, sealed OOS unaccessed and no executable\n"
            "authority. No active replacement strategy architecture, training-authorised\n"
            "correction or replacement observation epoch exists."
        ),
    }
    for old, new in replacements.items():
        if old not in report:
            raise RuntimeError(f"report patch target missing: {old!r}")
        report = report.replace(old, new, 1)
    path.write_text(report)


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
    result["latest_training_only_architecture"] = {
        "family_id": "causal-own-price-volatility-clustering-relaxation-opportunity-1h-v1",
        "pull_request": 979,
        "exact_tested_head": "ddaeb075dfdbe78e07f05b36b0a2b38f53285615",
        "workflow_run": 30752577260,
        "artifact_id": 8834954329,
        "artifact_sha256": "42af5528fbcfc600c6fc6eca3230028c64f2078d4ce345fcce5cc0add1ac33ad",
        "targets_passing": 0,
        "target_count": 2,
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "sealed_oos_accessed": False,
        "verdict": (
            "reject_causal_own_price_volatility_clustering_relaxation_"
            "information_premise_1h_v1"
        ),
        "correction_authority": False,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "no completed architecture has bilateral promotion authority; the latest "
            "own-price volatility-clustering-relaxation information premise was rejected "
            "with targets passing zero of two and candidate count zero, and no active "
            "replacement architecture exists"
        ),
    }
    result["next_strategy_action"] = (
        "advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at "
        "the next complete public 1H observation; do not rescue the rejected "
        "volatility-clustering-relaxation family, and freeze any materially "
        "orthogonal causal source contract and falsifiable temporal rule before "
        "feature or target-return access"
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
    machine["latest_training_diagnostic_verdict"] = result[
        "latest_training_only_architecture"
    ]["verdict"]

    prior.prior.write_result(output_dir, result)
    prior.prior.write_report(output_dir, result)
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
