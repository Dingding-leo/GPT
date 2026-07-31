from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_0500 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_466_800_000  # 2026-07-31T03:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_470_400_000  # 2026-07-31T04:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_474_000_000  # 2026-07-31T05:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_477_600_000  # 2026-07-31T06:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_456_000_000  # 2026-07-31T00:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "b9b990ff29574068078461885445f91d464fd6a9847f0f24acaafd6ba1979beb"
PRIOR_ARTIFACT_SHA256 = "00e2c824151e4f3d4ec65a442abae7da4a133ca8f49cb585a8a06699583b1974"


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
            lines.append("# Prospective simple-trend shadow update through 06:00 UTC on 31 July 2026")
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

Issue #767 and closed evidence PR #768 contain terminal rejection evidence for the exact
`entry-only-volatility-gated-cadence-state-1h-v1` candidate on the fresh TRX-USDT and
DOT-USDT cohort. Preserving daily B1 authority for exits removed the prior premature-exit
failure channel, but non-midnight high-volatility entries underperformed B1 in both markets,
increased turnover, and failed bilateral uncertainty gates. Transient endpoint-sign crossings
produced larger losses than persistent early onsets earned. No training-authorized correction
exists, and this BTC/ETH forward interval was not consumed to revise or rescue the rejected family.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 556
    result["window"]["updated_cumulative_realized_hours"] = 557
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["latest_terminal_candidate_context"] = {
        "issue": 767,
        "pull_request": 768,
        "family_id": "entry-only-volatility-gated-cadence-state-1h-v1",
        "status": "terminal_rejection_evidence_closed_unmerged",
        "workflow_run": 30611294305,
        "artifact_id": 8785660933,
        "artifact_sha256": "31b92b6d8cdca1530fbea30a97ae69759724762bda14ef2bd24a1c053f97a870",
        "result_sha256": "15cd00ac79d5bf48ede083b2c813278c418526e65f593776c34326d8a5da9f1e",
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "reason": (
            "Both fresh markets underperformed the daily B1 benchmark. Entry-only volatility gating removed "
            "premature exits but transient endpoint-sign crossings made the early-entry channel net adverse, "
            "increased turnover, and failed dependence-aware bilateral gates; no same-cohort rescue is authorized."
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
        "do not prospectively rescue the rejected entry-only volatility-gated cadence state family"
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
