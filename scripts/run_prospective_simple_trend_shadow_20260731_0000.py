from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260730_2300 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_445_200_000  # 2026-07-30T21:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_448_800_000  # 2026-07-30T22:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_452_400_000  # 2026-07-30T23:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_456_000_000  # 2026-07-31T00:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_434_400_000  # 2026-07-30T18:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "b1db9c66fae5d8a6fb56cbf65d4b4cb4eddc363d1d2fdd3bd2e27472c6aab92c"
PRIOR_ARTIFACT_SHA256 = "1aaea595597bdba70012dd80633d4f0d4e12d295aee54b7eb98afb8defc9f8d5"


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
        "Issue #753 and closed evidence PR #754 contain terminal rejection evidence for the exact "
        "daily 2,160H margin-acceleration confirmation candidate. BTC lost 52.65 percentage points "
        "of compounded development-OOS return versus B1, worsened drawdown and increased turnover "
        "from 45 to 328. ETH improved aggregate return, Sharpe and drawdown, but turnover rose from "
        "31 to 272 and edge per turnover collapsed from 280.36 to 35.28 bps. Profitable-fold breadth "
        "was only 4/12 and 6/12, profitable-year breadth 1/4 and 2/4, residual Sharpes were negative, "
        "and every dependence-aware lower bound was negative. The 24-hour slope condition repeatedly "
        "switched exposure inside persistent positive 2,160H regimes. This forward interval was not "
        "consumed to revise or rescue that family."
    )
    lines = []
    for line in report_path.read_text().splitlines():
        if line.startswith("# Prospective simple-trend shadow update through"):
            lines.append("# Prospective simple-trend shadow update through 00:00 UTC on 31 July 2026")
        elif line.startswith("Issue #748 and closed evidence PR #749"):
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
    result["window"]["prior_cumulative_realized_hours"] = 550
    result["window"]["updated_cumulative_realized_hours"] = 551
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 753,
        "pull_request": 754,
        "family_id": "daily-margin-acceleration-confirmation-1h-v1",
        "status": "terminal_rejection_evidence_closed_unmerged",
        "workflow_run": 30596226600,
        "artifact_id": 8780233710,
        "result_sha256": "df73a87ea587212a30e31234df0d264ac95d5a5bfb08f951455a96958fa0819b",
        "prospective_performance_consumed": False,
        "reason": (
            "BTC underperformed B1 on return, Sharpe, drawdown, turnover and edge efficiency. ETH's "
            "favourable aggregate point estimates failed turnover, edge-per-turnover, fold/year breadth, "
            "residual-Sharpe and dependence-aware uncertainty gates. The 24-hour slope condition caused "
            "high-frequency exposure switching inside persistent positive long-horizon regimes."
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
        "do not prospectively rescue the rejected daily margin-acceleration confirmation family"
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
