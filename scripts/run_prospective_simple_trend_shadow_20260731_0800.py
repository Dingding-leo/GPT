from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_0700 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_474_000_000  # 2026-07-31T05:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_477_600_000  # 2026-07-31T06:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_481_200_000  # 2026-07-31T07:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_484_800_000  # 2026-07-31T08:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_463_200_000  # 2026-07-31T02:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "f902f9fb8b14936bd3cba9014618240f00f0e66d43ce3bdeb0f519758b34de48"
PRIOR_ARTIFACT_SHA256 = "e89cc30042be9d1c9a7605549a49f94d54e78351abf2361b3b4ac1a8080e6c81"


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
            lines.append("# Prospective simple-trend shadow update through 08:00 UTC on 31 July 2026")
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

Issue #774 and closed evidence PR #775 evaluated the sole frozen
`dual-horizon-direct-forecast-consensus-1h-v1` candidate on UNI-USDT and AAVE-USDT.
The candidate is terminally rejected: development-OOS net returns were -76.00% and
-21.20% versus daily-B1 returns of +1.50% and +54.58%; forecast-versus-realised
correlations were negative at both 24H and 168H horizons in both markets; turnover
rose to 210 and 214; and every dependence-aware lower confidence bound was negative.
No market passed all preregistered gates. This result does not authorise a correction
to the nominated BTC/ETH policy, and the present forward interval is excluded from
same-cohort redesign or rescue.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 558
    result["window"]["updated_cumulative_realized_hours"] = 559
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 774,
        "pull_request": 775,
        "family_id": "dual-horizon-direct-forecast-consensus-1h-v1",
        "status": "terminally_rejected",
        "markets": ["UNI-USDT", "AAVE-USDT"],
        "candidate_performance_evaluated": True,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "markets_passing_all_gates": 0,
        "reason": (
            "Both fixed-market candidates failed return transport, turnover efficiency, temporal breadth, "
            "benchmark-relative residual quality, and dependence-aware uncertainty gates. The family is "
            "terminally rejected and cannot alter the current BTC/ETH observation epoch."
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
        "do not rescue the rejected dual-horizon forecast-consensus family; any new candidate must be separately "
        "preregistered on an availability-verified untouched cohort after rejected-family overlap audit"
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
