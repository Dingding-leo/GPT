from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_20260802_0800 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_650_400_000
REALIZED_DECISION_HOUR_MS = 1_785_654_000_000
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_654_000_000
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_657_600_000
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_639_600_000
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PAYOFF_END_OPEN_HOUR_MS = 1_785_661_200_000
PRIOR_RESULT_SHA256 = "21939b8d8ce0b2056aac182d5707a4233a8f30fb2e44a203c05daff592b708f0"
PRIOR_ARTIFACT_SHA256 = "918e9759bf8450307ca49ee0bd13b49f665bd8b9ebd751a6108165832756e06b"


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
        "through 08:00 UTC on 2 August 2026": "through 09:00 UTC on 2 August 2026",
        "The 07:00 signal bar was provider-confirmed": "The 08:00 signal bar was provider-confirmed",
        "The 08:00 candle supplied only its already-fixed open": "The 09:00 candle supplied only its already-fixed open",
        "end of the 07:00–08:00 open-to-open payoff": "end of the 08:00–09:00 open-to-open payoff",
    }
    for old, new in replacements.items():
        report = report.replace(old, new)
    path.write_text(report)


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["window"]["prior_cumulative_realized_hours"] = 607
    result["window"]["updated_cumulative_realized_hours"] = 608
    result["performance_accessed"] = False
    result["oos_accessed"] = False
    result["machine_readable_verdict"]["updated_cumulative_realized_hours"] = 608
    result["machine_readable_verdict"]["payoff_end_open_timestamp"] = iso_utc(
        PAYOFF_END_OPEN_HOUR_MS
    )
    result["prospective_lineage"]["prior_result_sha256"] = PRIOR_RESULT_SHA256
    result["prospective_lineage"]["prior_artifact_sha256"] = PRIOR_ARTIFACT_SHA256
    result["checkpoint_replication"] = {
        "type": "new_hour_after_exact_prior_checkpoint",
        "prior_pull_request": 959,
        "prior_workflow_run": 30739441527,
        "prior_artifact_id": 8830764761,
        "prior_result_sha256": PRIOR_RESULT_SHA256,
        "prior_artifact_sha256": PRIOR_ARTIFACT_SHA256,
        "policy_unchanged": True,
        "source_contract_unchanged": True,
        "fee_unchanged": True,
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the completed public-exogenous information programme closure found zero "
            "bilateral benchmark-relative, dependence-supported, or breadth-and-delay-supported "
            "groups, and no materially orthogonal replacement architecture is preregistered"
        ),
    }
    result["next_strategy_action"] = (
        "advance the unchanged independent BTC-USDT and ETH-USDT E2160 shadow at the "
        "next complete public 1H observation; open no replacement strategy until a materially "
        "orthogonal causal source contract and falsifiable temporal rule are frozen before "
        "feature or target-return access"
    )
    result["machine_readable_verdict"]["correction_permitted"] = False
    result["machine_readable_verdict"]["correction_applied"] = False
    result["machine_readable_verdict"]["policy_changed"] = False
    result["machine_readable_verdict"]["observation_epoch_restarted"] = False
    result["machine_readable_verdict"]["active_family_id"] = None
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
