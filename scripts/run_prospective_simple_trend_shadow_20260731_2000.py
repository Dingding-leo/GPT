from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_1900 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_517_200_000  # 2026-07-31T17:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_520_800_000  # 2026-07-31T18:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_524_400_000  # 2026-07-31T19:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_528_000_000  # 2026-07-31T20:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_506_400_000  # 2026-07-31T14:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "9bd3d20712e6712618aedef057742f707c9f4bc96470771001bfcc02e00acf26"
PRIOR_ARTIFACT_SHA256 = "a1645c8085f0acaa5b754c3b43de3aa3ecc5353fd639f45ad684871ca0ddb61d"


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
            lines.append("# Prospective simple-trend shadow update through 20:00 UTC on 31 July 2026")
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

Issue #822 and evidence PR #823 terminally reject the training-only
`lagged-return-range-response-resilience-opportunity-diagnostic-1h-v1-replication`
premise on the independently frozen, checksum-complete 2024-12 through 2025-12
cohort. All 26 public Binance SPOT archive/checksum pairs verified and 333 valid
next-day labels per market were scored. BTC gross/adverse rank correlations were
+0.0137/+0.0650 and ETH correlations were +0.0656/+0.1093, but every gross-return
confidence interval crossed zero, fold and month breadth failed, and gross
quintile ordering was non-monotonic in both markets. Common-calendar gross and
adverse correlation intervals were [-0.0555,+0.1315] and [-0.0214,+0.1904].
Weak downside-shape evidence was insufficient to authorise a cash gate or sizing
rule. Candidate count and parameter grid were zero, later/OOS data was not
accessed, and exactly 5 bps one way appeared only in independent target-label
economics. No lag, horizon, transform, threshold, market-specific rescue,
executable candidate, policy mutation, or observation-epoch restart is
authorised. The nominated BTC/ETH policy, chronology, fee model, and scorecard
remain immutable.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 570
    result["window"]["updated_cumulative_realized_hours"] = 571
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 822,
        "pull_request": 823,
        "family_id": "lagged-return-range-response-resilience-opportunity-diagnostic-1h-v1-replication",
        "status": "terminal_training_only_information_premise_rejected",
        "markets": ["BTCUSDT", "ETHUSDT"],
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "source_contract_complete": True,
        "archive_checksum_pairs_verified": 26,
        "valid_decisions_per_market": 333,
        "training_diagnostic_evaluated": True,
        "candidate_performance_evaluated": False,
        "oos_accessed": False,
        "later_data_accessed": False,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "6bf34008f37afbe36ea7c3310abf0f4fb354cdac",
        "workflow_run": 30664438915,
        "artifact_id": 8806394570,
        "artifact_sha256": "3790e2938c1cbef066a48ec6d7810b9e68121c86e4d4ce9d3606995ac9c33b52",
        "evidence_sha256": "7d7555863fd58692c54dc94a30373c595e213d8c4e1392b1533db5f66aea4fac",
        "source_manifest_sha256": "36a8296807e8b753bef613d5861a6e81a810deef0f44d2c295cb1e502ef5675f",
        "verdict": "reject_lagged_return_range_response_resilience_information_premise",
        "markets_passing_all_gates": 0,
        "rejection_evidence": {
            "BTCUSDT": {
                "gross_rank_correlation": 0.0137,
                "gross_rank_correlation_ci95": [-0.0955, 0.1108],
                "adverse_rank_correlation": 0.0650,
                "adverse_rank_correlation_ci95": [-0.0583, 0.1775],
                "positive_gross_folds": 3,
                "positive_adverse_folds": 5,
                "represented_folds": 11,
                "positive_gross_months": 4,
                "positive_adverse_months": 5,
                "represented_months": 11,
                "state_iqr": 0.1954,
                "high_minus_low_gross": 0.000615,
                "high_minus_low_adverse": 0.001148,
                "gross_quintile_index_rho": -0.8,
                "adverse_quintile_index_rho": 0.9,
            },
            "ETHUSDT": {
                "gross_rank_correlation": 0.0656,
                "gross_rank_correlation_ci95": [-0.0402, 0.1740],
                "adverse_rank_correlation": 0.1093,
                "adverse_rank_correlation_ci95": [-0.0073, 0.2201],
                "positive_gross_folds": 4,
                "positive_adverse_folds": 6,
                "represented_folds": 11,
                "positive_gross_months": 4,
                "positive_adverse_months": 7,
                "represented_months": 11,
                "state_iqr": 0.1899,
                "high_minus_low_gross": 0.005729,
                "high_minus_low_adverse": 0.004055,
                "gross_quintile_index_rho": 0.5,
                "adverse_quintile_index_rho": 0.7,
            },
            "common_calendar_gross_rank_correlation_ci95": [-0.0555, 0.1315],
            "common_calendar_adverse_rank_correlation_ci95": [-0.0214, 0.1904],
            "valid_bootstrap_draws": 5000,
        },
        "reason": (
            "the frozen lagged signed-return/range-response state failed bilateral gross-return information, "
            "temporal breadth, and quintile-monotonicity gates on an independently verified replication cohort"
        ),
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the only completed training diagnostic was rejected bilaterally and authorised no executable rule"
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
        "do not rescue the rejected lagged range-response family; any distinct strategy correction must be "
        "separately preregistered on an untouched immutable 1H contract and pass bilateral information gates "
        "before OOS access or executable evaluation"
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
