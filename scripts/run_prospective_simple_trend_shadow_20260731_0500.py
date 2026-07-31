from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_0400 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_463_200_000  # 2026-07-31T02:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_466_800_000  # 2026-07-31T03:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_470_400_000  # 2026-07-31T04:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_474_000_000  # 2026-07-31T05:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_452_400_000  # 2026-07-30T23:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "7e57954a1bf454a2f0f116eb78e6cea06db94c0d4292791172498366a16d1ea5"
PRIOR_ARTIFACT_SHA256 = "714884ece3bb3cdc7e7f219d4e6ba9d25cfc51bf933a6f8460a8fb70de999024"


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
            lines.append("# Prospective simple-trend shadow update through 05:00 UTC on 31 July 2026")
        else:
            lines.append(line)
    report = "\n".join(lines) + "\n"
    correction_start = report.index("Issue #761 and closed evidence PR #762")
    correction_end = report.index("\n\n## Abort conditions and verdict", correction_start)
    active_correction = (
        "Issue #764 and draft PR #765 contain the sole preregistered training-only evaluation of the exact "
        "`volatility-gated-cadence-1h-v1` candidate on the fresh ALGO-USDT and ATOM-USDT cohort. The rule remains "
        "under terminal evaluation at this acquisition checkpoint. No training-authorized correction verdict has "
        "been issued, the immutable BTC/ETH nominated policy is unchanged, and this forward interval is not "
        "consumed for candidate selection, rescue tuning, or market filtering."
    )
    report_path.write_text(report[:correction_start] + active_correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 555
    result["window"]["updated_cumulative_realized_hours"] = 556
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 764,
        "pull_request": 765,
        "family_id": "volatility-gated-cadence-1h-v1",
        "status": "preregistered_training_evaluation_in_progress",
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "reason": (
            "The sole fresh-cohort training evaluation was not terminal at acquisition; therefore no correction "
            "is authorized and the nominated BTC/ETH policy and observation epoch remain unchanged."
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
        "continue the identical frozen 2160H benchmark-shadow epoch at the next complete public 1H observation; "
        "separately complete the preregistered volatility-gated cadence evaluation without using BTC/ETH forward data"
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
