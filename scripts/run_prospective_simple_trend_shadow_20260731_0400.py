from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_0300 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_459_600_000  # 2026-07-31T01:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_463_200_000  # 2026-07-31T02:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_466_800_000  # 2026-07-31T03:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_470_400_000  # 2026-07-31T04:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_448_800_000  # 2026-07-30T22:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "643edc584d1ed6eadfbad4dd16dba4627b395ebabd30e5ae3d4ba1932436a6a2"
PRIOR_ARTIFACT_SHA256 = "8a5a2d792ab425c61c4c9dcef05e160f06de6c1c49b063a371616d66cd31dd25"


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
            lines.append("# Prospective simple-trend shadow update through 04:00 UTC on 31 July 2026")
        else:
            lines.append(line)
    report = "\n".join(lines) + "\n"
    correction_start = report.index("Issue #757 and closed evidence PR #758")
    correction_end = report.index("\n\n## Abort conditions and verdict", correction_start)
    active_correction = (
        "Issue #761 and closed evidence PR #762 contain terminal rejection evidence for the exact "
        "`reference-uplift-exit-bridge-1h-v1` candidate on the fresh preregistered BCH-USDT and LINK-USDT cohort. "
        "BCH underperformed its frozen B1 benchmark and LINK's favourable development-OOS point estimate was "
        "entirely concentrated in one 2023 bridge event. Both markets failed profitable-fold breadth, full-sample "
        "viability and dependence-aware uncertainty gates; zero of two markets passed every preregistered gate. "
        "No training-authorized correction trigger exists, and this new BTC/ETH forward interval was not consumed "
        "to revise or rescue the rejected family."
    )
    report_path.write_text(report[:correction_start] + active_correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 554
    result["window"]["updated_cumulative_realized_hours"] = 555
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 761,
        "pull_request": 762,
        "family_id": "reference-uplift-exit-bridge-1h-v1",
        "status": "terminal_rejection_evidence_closed_unmerged",
        "workflow_run": 30605099932,
        "artifact_id": 8783389248,
        "result_sha256": "88c4497e39d4bca020776c3d05e35e5645f3a5de685121cf74bbb66558992567",
        "prospective_performance_consumed": False,
        "reason": (
            "The same-instrument reference-uplift bridge underperformed B1 on BCH and produced a favourable LINK "
            "development-OOS result concentrated in one event; both markets failed breadth, absolute full-sample "
            "viability and dependence-aware uncertainty gates."
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
        "do not prospectively rescue the rejected reference-uplift exit bridge family"
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
