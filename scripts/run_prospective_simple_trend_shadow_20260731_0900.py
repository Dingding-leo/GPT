from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_0800 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_477_600_000  # 2026-07-31T06:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_481_200_000  # 2026-07-31T07:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_484_800_000  # 2026-07-31T08:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_488_400_000  # 2026-07-31T09:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_466_800_000  # 2026-07-31T03:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "656e9252fdc660a9062334f8c4760836aad35019f03c6e6d0a9f6cf56fe2ae32"
PRIOR_ARTIFACT_SHA256 = "3960d27e2153d67ac97c7d721d6ae50eff919981908b9f138d8f26b9bd82e540"


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
            lines.append("# Prospective simple-trend shadow update through 09:00 UTC on 31 July 2026")
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

Issue #779 and draft evidence PR #780 evaluated the sole frozen
`trend-conditioned-weekly-loss-probability-veto-1h-v1` candidate on NEAR-USDT and
SAND-USDT. The family is terminally rejected. NEAR candidate development-OOS net
return was +113.30% versus B1 +359.98%, Sharpe 0.715 versus 1.046, turnover 47 versus
39, and edge per turnover 332.25 versus 631.76 bps. SAND improved aggregate point
estimates (+28.94% versus +0.74%, Sharpe 0.441 versus 0.329), but had only 3/12
profitable folds, 2/4 profitable years, 79.73% positive-fold concentration, a negative
full-sample return and uncertainty intervals crossing zero. NEAR had 5/12 folds,
2/4 years, residual Sharpe -1.019 and negative lower bounds. Zero of two markets
passed all gates. No threshold, confidence level, neighbour count, feature, cadence,
market or fee rescue is authorised, and the candidate cannot correct the nominated
BTC/ETH policy.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 559
    result["window"]["updated_cumulative_realized_hours"] = 560
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 779,
        "pull_request": 780,
        "family_id": "trend-conditioned-weekly-loss-probability-veto-1h-v1",
        "status": "terminally_rejected",
        "markets": ["NEAR-USDT", "SAND-USDT"],
        "candidate_performance_evaluated": True,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "markets_passing_all_gates": 0,
        "workflow_run": 30622844310,
        "artifact_id": 8790248290,
        "artifact_sha256": "5bd0142cb3debf38d853d8e97a7fdb89cb4681860f528f0e145cf3ffb3e067be",
        "result_sha256": "a7541d3b2c760d7fed4f612da6d934f9bd4f2de6f4c977d80c77a993e7fad776",
        "verdict": "reject_trend_conditioned_weekly_loss_probability_veto_family",
        "reason": (
            "NEAR materially underperformed B1 with higher turnover and negative residual quality. SAND "
            "improved aggregate point estimates but failed temporal breadth, concentration, full-sample and "
            "dependence-aware uncertainty gates. Zero of two markets passed the frozen bilateral scorecard."
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
        "close the rejected NEAR/SAND weekly loss-probability veto evidence without merge and do not rescue its "
        "threshold, confidence level, neighbour count, features, cadence, cohort or fee treatment"
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
