from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260730_2200 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_441_600_000  # 2026-07-30T20:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_445_200_000  # 2026-07-30T21:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_448_800_000  # 2026-07-30T22:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_452_400_000  # 2026-07-30T23:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_430_800_000  # 2026-07-30T17:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "738b71c0bc60b8aaa79a102a0affdb4bfe8f5af802159870359b586cff1befe7"
PRIOR_ARTIFACT_SHA256 = "d26444e58f1d57671d4ed98863a83c30b06d345ebd446eb7db2acc9feeadfe00"


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
    replacement = (
        "Issue #748 and closed evidence PR #749 contain terminal rejection evidence for the exact "
        "two-loss payoff change-point reset selector. BTC improved edge per turnover while reducing "
        "turnover, but materially lost compounded return and worsened drawdown; ETH lost return, "
        "drawdown and edge efficiency. Profitable-fold breadth was only 5/12 and 6/12, residual "
        "Sharpes were negative, every per-market dependence-aware lower bound was negative, and the "
        "common-block return and Sharpe intervals were wholly negative. The reset cold start rejected "
        "profitable first post-reset episodes, then a single positive episode could reopen selection "
        "before adverse payoff was disproven. This forward interval was not consumed to revise or "
        "rescue that family."
    )
    lines = []
    for line in report_path.read_text().splitlines():
        if line.startswith("# Prospective simple-trend shadow update through"):
            lines.append("# Prospective simple-trend shadow update through 23:00 UTC")
        elif line.startswith("Issue #745 and closed evidence PR #746"):
            lines.append(replacement)
        else:
            lines.append(line)
    report_path.write_text("\n".join(lines) + "\n")


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 549
    result["window"]["updated_cumulative_realized_hours"] = 550
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 748,
        "pull_request": 749,
        "family_id": "two-loss-payoff-change-point-reset-selector-1h-v1",
        "status": "terminal_rejection_evidence_closed_unmerged",
        "prospective_performance_consumed": False,
        "reason": (
            "The reset selector underperformed the frozen B1 benchmark on compounded return in both "
            "markets, lacked profitable-fold breadth, had negative residual Sharpes and failed every "
            "dependence-aware uncertainty gate. Reset cold starts rejected profitable first episodes, "
            "while later sparse positive episodes could reopen selection before adverse payoff was disproven."
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
        "do not prospectively rescue the rejected two-loss payoff change-point reset selector family"
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
