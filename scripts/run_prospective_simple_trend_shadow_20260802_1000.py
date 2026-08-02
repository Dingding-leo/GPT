from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_0900 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_654_000_000
REALIZED_DECISION_HOUR_MS = 1_785_657_600_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_657_600_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_661_200_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_643_200_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_664_800_000
PRIOR_RESULT_SHA256 = "442bd404a3a30d4a78d0ae70cbe8c386a53254f68452ae9423fa576d1e6cd240"
PRIOR_ARTIFACT_SHA256 = "b7a564d42e737f260cf0e785f32f16c716d5487a735b07a5eec819aa8bf45767"


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
        "through 09:00 UTC on 2 August 2026": "through 10:00 UTC on 2 August 2026",
        "The 08:00 signal bar was provider-confirmed": "The 09:00 signal bar was provider-confirmed",
        "The 09:00 candle supplied only its already-fixed open": "The 10:00 candle supplied only its already-fixed open",
        "end of the 08:00–09:00 open-to-open payoff": "end of the 09:00–10:00 open-to-open payoff",
    }
    for old, new in replacements.items():
        report = report.replace(old, new)
    path.write_text(report)


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["window"]["prior_cumulative_realized_hours"] = 608
    result["window"]["updated_cumulative_realized_hours"] = 609
    result["performance_accessed"] = False
    result["oos_accessed"] = False
    result["machine_readable_verdict"]["updated_cumulative_realized_hours"] = 609
    result["machine_readable_verdict"]["payoff_end_open_timestamp"] = iso_utc(
        PAYOFF_END_OPEN_HOUR_MS
    )
    result["prospective_lineage"]["prior_result_sha256"] = PRIOR_RESULT_SHA256
    result["prospective_lineage"]["prior_artifact_sha256"] = PRIOR_ARTIFACT_SHA256
    result["checkpoint_replication"] = {
        "type": "new_hour_after_exact_prior_checkpoint",
        "prior_pull_request": 962,
        "prior_workflow_run": 30741466624,
        "prior_artifact_id": 8831424143,
        "prior_result_sha256": PRIOR_RESULT_SHA256,
        "prior_artifact_sha256": PRIOR_ARTIFACT_SHA256,
        "policy_unchanged": True,
        "source_contract_unchanged": True,
        "fee_unchanged": True,
    }
    result["active_alpha_context"] = {
        "issue": 963,
        "pull_request": 964,
        "family_id": "causal-fixed-universe-directional-diffusion-opportunity-1h-v1",
        "classification": "training_information_premise_only",
        "status": "separate_training_only_diagnostic_not_terminal_at_checkpoint_freeze",
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
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "no completed architecture has bilateral promotion authority; the separate "
            "fixed-universe directional-diffusion diagnostic is training-information-only, "
            "has candidate count zero, and cannot mutate this checkpoint even if its "
            "information premise passes"
        ),
    }
    result["next_strategy_action"] = (
        "publish the terminal training-only disposition of issue 963 / PR 964, then advance "
        "the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at the next complete "
        "public 1H observation; any passing information premise requires a separately "
        "predeclared executable candidate and a newly frozen observation epoch"
    )
    result["machine_readable_verdict"]["correction_permitted"] = False
    result["machine_readable_verdict"]["correction_applied"] = False
    result["machine_readable_verdict"]["policy_changed"] = False
    result["machine_readable_verdict"]["observation_epoch_restarted"] = False
    result["machine_readable_verdict"]["active_family_id"] = result[
        "active_alpha_context"
    ]["family_id"]
    result["machine_readable_verdict"]["active_family_status"] = result[
        "active_alpha_context"
    ]["status"]
    prior.write_outputs(output_dir, result)
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
