from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_1000 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_484_800_000  # 2026-07-31T08:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_488_400_000  # 2026-07-31T09:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_492_000_000  # 2026-07-31T10:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_495_600_000  # 2026-07-31T11:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_474_000_000  # 2026-07-31T05:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "ff13d9bcf7c522c11cf6ecab3003ad543b085e0c760048739d568ff3e9b725d6"
PRIOR_ARTIFACT_SHA256 = "5d6ae840c95d4886e51f35bac3e4932eff63685f93f7f1583e2d31574b16ebb0"


def configure_frozen_epoch() -> None:
    prior.PREVIOUS_DECISION_HOUR_MS = PREVIOUS_DECISION_HOUR_MS
    prior.REALIZED_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
    prior.PRIOR_REPORTED_SIGNAL_HOUR_MS = PRIOR_REPORTED_SIGNAL_HOUR_MS
    prior.LATEST_COMPLETE_SIGNAL_HOUR_MS = LATEST_COMPLETE_SIGNAL_HOUR_MS
    prior.RECENT_WINDOW_FIRST_DECISION_HOUR_MS = RECENT_WINDOW_FIRST_DECISION_HOUR_MS
    prior.RECENT_WINDOW_LAST_DECISION_HOUR_MS = RECENT_WINDOW_LAST_DECISION_HOUR_MS
    prior.PRIOR_RESULT_SHA256 = PRIOR_RESULT_SHA256
    prior.PRIOR_ARTIFACT_SHA256 = PRIOR_ARTIFACT_SHA256


def write_report(output_dir: Path, result: dict[str, Any]) -> None:
    prior.write_report(output_dir, result)
    report_path = output_dir / "report.md"
    lines = []
    for line in report_path.read_text().splitlines():
        if line.startswith("# Prospective simple-trend shadow update through"):
            lines.append("# Prospective simple-trend shadow update through 11:00 UTC on 31 July 2026")
        else:
            lines.append(line)
    report = "\n".join(lines) + "\n"
    correction_heading = "## Correction protocol\n"
    correction_start = report.index(correction_heading) + len(correction_heading)
    correction_end = report.index("\n## Abort conditions and verdict", correction_start)
    correction = """

- Correction permitted: `False`
- Correction applied: `False`
- Policy changed: `false`
- Observation epoch restarted: `false`

Issue #787 and draft evidence PR #788 contain the sole currently active
`analog-conditioned-weekly-b1-sleeve-payoff-sizing-1h-v1` experiment on the fixed
KSM-USDT and IOTA-USDT cohort. The candidate uses exact fee-adjusted future 168H
B1-sleeve payoff labels, but its exact-head public-data evaluation has not yet
produced a terminal bilateral acceptance verdict. Candidate performance is not used
in this forward interval and no training-authorised correction exists. The nominated
BTC/ETH policy, fee model, chronology, scorecard and observation epoch therefore
remain immutable. A terminal candidate failure must be rejected without rescue; a
terminal supporting result would still require a separately frozen prospective epoch
and could not retroactively alter this observation.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 561
    result["window"]["updated_cumulative_realized_hours"] = 562
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 787,
        "pull_request": 788,
        "family_id": "analog-conditioned-weekly-b1-sleeve-payoff-sizing-1h-v1",
        "status": "exact_head_evaluation_in_progress",
        "markets": ["KSM-USDT", "IOTA-USDT"],
        "candidate_performance_evaluated": False,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "8a48d1d5104dab1ede3717a21abb83ffe6e724a8",
        "workflow_run": 30629936423,
        "verdict": None,
        "reason": (
            "the preregistered candidate has no terminal bilateral acceptance verdict; its performance and "
            "gates are unavailable to this forward update, so it cannot modify the immutable BTC/ETH epoch"
        ),
    }
    exposed = any(market["realized_interval"]["position"] == 1 for market in result["markets"])
    result["historical_selection_relationship_status"] = {
        "assessable_in_new_interval": exposed,
        "reason": (
            "the new interval contains frozen long exposure and contributes conditional-long forward evidence"
            if exposed
            else "the new interval is cash-only, so it supplies no realised conditional-long return and cannot validate historical selection persistence"
        ),
    }
    result["next_strategy_action"] = (
        "continue the identical BTC/ETH 2160H prospective shadow at the next complete public 1H observation; "
        "await the terminal preregistered KSM/IOTA candidate verdict without using its in-progress evidence "
        "to change this epoch, and reject it without same-cohort rescue if any frozen gate fails"
    )
    base.write_outputs(output_dir, result)
    write_report(output_dir, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default=os.environ.get("OKX_BASE_URL", "https://www.okx.com"))
    args = parser.parse_args()
    result = run(args.output_dir, args.base_url.rstrip("/"))
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
