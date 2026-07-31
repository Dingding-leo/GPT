from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_0100 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_452_400_000  # 2026-07-30T23:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_456_000_000  # 2026-07-31T00:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_459_600_000  # 2026-07-31T01:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_463_200_000  # 2026-07-31T02:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_441_600_000  # 2026-07-30T20:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "2b1b05da39920b1794fb0ed0059e408a32356d798f892be59e3dc3996e78d6d8"
PRIOR_ARTIFACT_SHA256 = "5d1e6753609b8b12fdbc7c4f4798e8ab1e292278f598fbc983afb19fdee43288"


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
            lines.append("# Prospective simple-trend shadow update through 02:00 UTC on 31 July 2026")
        else:
            lines.append(line)
    report_path.write_text("\n".join(lines) + "\n")


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 552
    result["window"]["updated_cumulative_realized_hours"] = 553
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
