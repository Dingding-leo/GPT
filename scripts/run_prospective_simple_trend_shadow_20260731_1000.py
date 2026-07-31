from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_0900 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_481_200_000  # 2026-07-31T07:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_484_800_000  # 2026-07-31T08:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_488_400_000  # 2026-07-31T09:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_492_000_000  # 2026-07-31T10:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_470_400_000  # 2026-07-31T04:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "8627e795a0ef3a59ff9d90bcedc0000ab945e13aed0c61066d9199773ec61447"
PRIOR_ARTIFACT_SHA256 = "ea37d64b0cab4ef818296536394f6e991451e4d2b755e733141fa879cf2dcdd1"


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
            lines.append("# Prospective simple-trend shadow update through 10:00 UTC on 31 July 2026")
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

Issue #782 and closed evidence PR #783 evaluated the sole frozen
`weekly-payoff-efficiency-sizing-1h-v1` candidate on ICP-USDT and XLM-USDT. The
family is terminally rejected. ICP candidate development-OOS net return was -18.30%
versus B1 -15.86%, Sharpe 0.299 versus 0.316, turnover 45 versus 46, and edge per
turnover 152.41 versus 159.03 bps. XLM improved drawdown and reduced turnover but
returned +26.07% versus B1 +72.75%, Sharpe 0.427 versus 0.614, and edge per turnover
228.29 versus 263.12 bps. Breadth was only 4/12 profitable folds for each market;
profitable years were 1/4 for ICP and 3/4 for XLM. Residual Sharpes were -0.256 and
-0.795, and every dependence-aware lower confidence bound was negative. Zero of two
markets passed all gates. The expanding payoff-efficiency sign changed only once in
each market and lagged regime recovery, cutting positive-tail continuation rather
than identifying adverse weeks. No threshold, sizing map, cadence, history reset,
cohort, market-specific or fee rescue is authorised, and the candidate cannot correct
the nominated BTC/ETH policy.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 560
    result["window"]["updated_cumulative_realized_hours"] = 561
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 782,
        "pull_request": 783,
        "family_id": "weekly-payoff-efficiency-sizing-1h-v1",
        "status": "terminally_rejected",
        "markets": ["ICP-USDT", "XLM-USDT"],
        "candidate_performance_evaluated": True,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "markets_passing_all_gates": 0,
        "workflow_run": 30625205060,
        "artifact_id": 8791167598,
        "artifact_sha256": "9e2861743648542d88f6b908478c2914fe449122d596ead8a0cca6ff39af518d",
        "result_sha256": "920cfdb6c6830ded27be0d2bdcb10ea908858cbaf37a27fd2b6424fce5a54f1b",
        "verdict": "reject_weekly_payoff_efficiency_sizing_family",
        "reason": (
            "ICP underperformed B1 and XLM sacrificed most of B1's positive-tail continuation despite lower "
            "risk and turnover. Both markets failed temporal breadth, residual quality and dependence-aware "
            "uncertainty gates; zero of two markets passed the frozen bilateral scorecard."
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
        "do not rescue the rejected ICP/XLM weekly payoff-efficiency sizing family or alter its sizing map, "
        "cadence, history treatment, cohort or fee model"
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
