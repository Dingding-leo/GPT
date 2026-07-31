from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_0600 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_470_400_000  # 2026-07-31T04:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_474_000_000  # 2026-07-31T05:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_477_600_000  # 2026-07-31T06:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_481_200_000  # 2026-07-31T07:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_459_600_000  # 2026-07-31T01:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "0fe7c463ebffaa903a0c7d51e174c76c86ebe3c29c348d86017485fa25adfd53"
PRIOR_ARTIFACT_SHA256 = "98d9c7ffbb95aaf7957061de66cb40a2627ccf4bab9d7ea47d6f7a13d6630bb9"


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
            lines.append("# Prospective simple-trend shadow update through 07:00 UTC on 31 July 2026")
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

Issue #770 preregisters the sole active strategy-facing experiment,
`three-observation-intraday-onset-survival-1h-v1`, on fresh EOS-USDT and XLM-USDT.
It tests whether a positive 2,160H endpoint recross must survive three consecutive completed
hourly observations before an early non-midnight entry, while daily B1 remains authoritative
for exits. The protocol was frozen before source acquisition and candidate performance remains
unseen. It is not an authorised correction to the nominated BTC/ETH prospective policy, and
this forward interval is excluded from candidate fitting, selection, or rescue.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 557
    result["window"]["updated_cumulative_realized_hours"] = 558
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 770,
        "pull_request": None,
        "family_id": "three-observation-intraday-onset-survival-1h-v1",
        "status": "preregistered_active_performance_unseen",
        "markets": ["EOS-USDT", "XLM-USDT"],
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "reason": (
            "The frozen candidate has not yet acquired or scored its fresh cohort. It may be accepted or rejected "
            "only under issue #770's bilateral predeclared gates and cannot alter the current BTC/ETH epoch."
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
        "execute issue #770's frozen three-observation onset-survival candidate on fresh EOS/XLM public 1H data; "
        "continue the identical BTC/ETH 2160H shadow at the next complete observation and do not use either result for same-cohort rescue"
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
