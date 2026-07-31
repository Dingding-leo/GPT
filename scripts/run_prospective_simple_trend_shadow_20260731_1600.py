from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_1500 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_502_800_000  # 2026-07-31T13:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_506_400_000  # 2026-07-31T14:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_510_000_000  # 2026-07-31T15:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_513_600_000  # 2026-07-31T16:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_492_000_000  # 2026-07-31T10:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "ee67965129e2c58d79aed7c5357a68df6b0c2cea9ce40955d26d48f6caceace0"
PRIOR_ARTIFACT_SHA256 = "d68a745cb5f2b9bad1988b481404b6ea718e4148e1aacddd0ca2e8a9df301dab"


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
            lines.append("# Prospective simple-trend shadow update through 16:00 UTC on 31 July 2026")
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

Issue #808 and evidence PR #809 reject the training-only
`positive-regime-opportunity-stationarity-closure-1h-v1` premise on canonical
BTC-USDT and ETH-USDT history. Candidate count and parameter grid were zero,
development OOS remained unread, and no executable strategy was created. Mean
24H B1-long opportunity was positive and several fold/year breadth checks
passed, but only three BTC and four ETH positive regimes were available,
complete-regime bootstrap lower bounds crossed zero, and the largest regime
accounted for more than 53% of BTC and 65% of ETH absolute gross contribution.
Thus the apparent pooled edge is not stationarity-supported and cannot
Authorize a selector or sizing correction. No regime exclusion, duration
filter, weighting change, alternate horizon, threshold, target, fee, market
substitution, OOS access, or executable rescue is authorised. The nominated
BTC/ETH policy, fee model, chronology, scorecard, and observation epoch remain
immutable.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 566
    result["window"]["updated_cumulative_realized_hours"] = 567
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 808,
        "pull_request": 809,
        "family_id": "positive-regime-opportunity-stationarity-closure-1h-v1",
        "status": "terminal_training_only_architecture_premise_rejected",
        "markets": ["BTC-USDT", "ETH-USDT"],
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "source_acquired": True,
        "training_diagnostic_evaluated": True,
        "candidate_performance_evaluated": False,
        "oos_accessed": False,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "36c4b5ae56765e734f08d812150df2ec21c40a2f",
        "verdict": "reject_positive_regime_opportunity_stationarity_premise",
        "markets_passing_all_gates": 0,
        "rejection_evidence": {
            "BTC-USDT": {
                "regime_count": 3,
                "scored_labels": 247,
                "positive_mean_gross_regimes": 2,
                "positive_mean_net_regimes": 2,
                "median_regime_mean_gross": 0.02109493,
                "median_regime_mean_net": 0.02009493,
                "equal_weight_mean_gross": 0.01735463,
                "equal_weight_mean_net": 0.01635463,
                "day_weight_mean_gross": 0.01326783,
                "day_weight_mean_net": 0.01226783,
                "max_absolute_gross_contribution_share": 0.53516625,
                "max_positive_gross_contribution_share": 0.53516625,
                "positive_gross_folds": 5,
                "positive_net_folds": 5,
                "represented_years": 4,
                "positive_gross_years": 3,
                "positive_net_years": 3,
                "failed_gates": ["dependence_aware_uncertainty", "non_dominance"],
            },
            "ETH-USDT": {
                "regime_count": 4,
                "scored_labels": 273,
                "positive_mean_gross_regimes": 3,
                "positive_mean_net_regimes": 3,
                "median_regime_mean_gross": 0.01199393,
                "median_regime_mean_net": 0.01099393,
                "equal_weight_mean_gross": 0.01224331,
                "equal_weight_mean_net": 0.01124331,
                "day_weight_mean_gross": 0.02063815,
                "day_weight_mean_net": 0.01963815,
                "max_absolute_gross_contribution_share": 0.65037079,
                "max_positive_gross_contribution_share": 0.65037079,
                "positive_gross_folds": 5,
                "positive_net_folds": 5,
                "represented_years": 4,
                "positive_gross_years": 3,
                "positive_net_years": 3,
                "failed_gates": ["dependence_aware_uncertainty", "non_dominance"],
            },
        },
        "reason": (
            "pooled B1 opportunity was positive but complete-regime uncertainty and contribution "
            "concentration failed bilaterally; only three BTC and four ETH regimes were observed"
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
        "do not rescue the rejected positive-regime stationarity premise; any distinct candidate must be "
        "separately preregistered, materially orthogonal, and evaluated without OOS access"
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
