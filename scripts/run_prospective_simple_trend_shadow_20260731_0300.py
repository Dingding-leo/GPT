from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_0200 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_456_000_000  # 2026-07-31T00:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_459_600_000  # 2026-07-31T01:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_463_200_000  # 2026-07-31T02:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_466_800_000  # 2026-07-31T03:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_445_200_000  # 2026-07-30T21:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "86a83445f1c6fd9e7d8b7cc70325acd27e41b624f4801ca14b6652885e039b6f"
PRIOR_ARTIFACT_SHA256 = "a8f79cc7af1019ef043140cc145ec762995fef4578a479c0ef1148969f9cd4d2"


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
            lines.append("# Prospective simple-trend shadow update through 03:00 UTC on 31 July 2026")
        else:
            lines.append(line)
    report = "\n".join(lines) + "\n"
    correction_start = report.index("Issue #753 and closed evidence PR #754")
    correction_end = report.index("\n\n## Abort conditions and verdict", correction_start)
    active_correction = (
        "Issue #757 and closed evidence PR #758 contain terminal rejection evidence for the exact "
        "`beta-sign-soft-exit-sleeve-1h-v1` candidate on the fresh preregistered SOL-USDT and XRP-USDT cohort. "
        "The posterior sleeve improved benchmark-relative return, Sharpe, drawdown, turnover and edge per "
        "turnover in both markets, but XRP remained negative in development OOS, both candidates were negative "
        "over the full scored sample, profitable-fold/year breadth and concentration gates failed, and every "
        "per-market dependence-aware lower confidence bound remained non-positive. No training-authorized "
        "correction trigger exists, and this new BTC/ETH forward interval was not consumed to revise or rescue "
        "the rejected family."
    )
    report_path.write_text(report[:correction_start] + active_correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 553
    result["window"]["updated_cumulative_realized_hours"] = 554
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 757,
        "pull_request": 758,
        "family_id": "beta-sign-soft-exit-sleeve-1h-v1",
        "status": "terminal_rejection_evidence_closed_unmerged",
        "workflow_run": 30599723593,
        "artifact_id": None,
        "result_sha256": "d232616f06b2a6fecdd91fc39693f57bf2feb494b374af369743ad7d73f14dc0",
        "prospective_performance_consumed": False,
        "reason": (
            "The same-instrument Beta-sign posterior improved benchmark-relative point estimates, turnover and "
            "edge efficiency on fresh SOL-USDT and XRP-USDT, but both full-sample candidates were negative, "
            "temporal gains were concentrated, breadth and concentration gates failed, and every per-market "
            "dependence-aware lower bound remained non-positive."
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
        "do not prospectively rescue the rejected Beta-sign soft exit sleeve family"
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
