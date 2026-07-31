from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_1100 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_488_400_000  # 2026-07-31T09:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_492_000_000  # 2026-07-31T10:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_495_600_000  # 2026-07-31T11:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_499_200_000  # 2026-07-31T12:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_477_600_000  # 2026-07-31T06:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "fbd1d4917a19c79874e3368666c81978364cbd600d6f41024d955ee425dbdcaa"
PRIOR_ARTIFACT_SHA256 = "c03a749783889bee05ba07815be351b49be4d15df529cdf82dc5092c0d1ff52d"


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
            lines.append("# Prospective simple-trend shadow update through 12:00 UTC on 31 July 2026")
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

Issue #792 and evidence PR #793 contain the exact frozen
`lagged-realised-b1-payoff-state-sizing-1h-v1` continuation on MKR-USDT and
YFI-USDT. Exact-head code validation passed, but immutable public-data acquisition
failed before strategy execution because OKX returned `51001` for the first fixed
market, MKR-USDT. YFI-USDT was not reached. No source artifact, strategy path,
performance metric, fee, turnover, fold/year result, bootstrap draw, or acceptance
gate was produced. The preregistered no-third-cohort rule therefore terminally
aborts the family. Candidate performance was not consumed and no training-authorised
correction exists. The nominated BTC/ETH policy, fee model, chronology, scorecard,
and observation epoch remain immutable.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 562
    result["window"]["updated_cumulative_realized_hours"] = 563
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 792,
        "pull_request": 793,
        "family_id": "lagged-realised-b1-payoff-state-sizing-1h-v1",
        "status": "terminal_preperformance_abort_public_source_unavailable",
        "markets": ["MKR-USDT", "YFI-USDT"],
        "source_acquired": False,
        "candidate_performance_evaluated": False,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "f5dafbe4a0adaea5001f86eaa762a91ea71ed5da",
        "workflow_run": 30631829928,
        "verdict": "abort_reject_frozen_candidate_public_source_unavailable",
        "reason": (
            "OKX returned 51001 for preregistered MKR-USDT before any immutable source or strategy output existed; "
            "YFI-USDT was not reached and the no-third-cohort rule prohibits substitution or shortened history"
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
        "do not rescue the terminally aborted MKR/YFI lagged-payoff family, and preregister any materially distinct "
        "candidate only after public-instrument and required-history availability are verified without inspecting performance"
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
