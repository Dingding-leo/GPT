from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_1200 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_492_000_000  # 2026-07-31T10:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_495_600_000  # 2026-07-31T11:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_499_200_000  # 2026-07-31T12:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_502_800_000  # 2026-07-31T13:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_481_200_000  # 2026-07-31T07:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "61d912e2a1805dc47bcbe7529971c043e596af6533018d8a114ddc9407d85c0f"
PRIOR_ARTIFACT_SHA256 = "e6b3bb297808e3d57dff785f953a5187fa9ff0688f8338f7ed51667d9b303a25"


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
            lines.append("# Prospective simple-trend shadow update through 13:00 UTC on 31 July 2026")
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

Issue #795 and evidence PR #796 close the exact training-only
`lag1-self-contained-b1-payoff-memory-closure-1h-v1` premise on canonical
BTC-USDT and ETH-USDT data. Candidate count was zero and OOS was prohibited.
Both point correlations and both conditional next-payoff magnitude deltas were
negative; each market supported positive lag-1 correlation in only 2/6 complete
training folds and 1/3 calendar years, and the positive prior-payoff state was
below the frozen minimum sample count. The apparent positive sign-transition
delta was partly an inactivity-state effect and did not transport to payoff
magnitude. Markets passing every gate were 0/2. The premise is terminally
rejected, so no longer lag, smoothing, alternate sign boundary, market
substitution, exposure remapping, or prospective correction is authorised.
The nominated BTC/ETH policy, fee model, chronology, scorecard, and observation
epoch remain immutable.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 563
    result["window"]["updated_cumulative_realized_hours"] = 564
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 795,
        "pull_request": 796,
        "family_id": "lag1-self-contained-b1-payoff-memory-closure-1h-v1",
        "status": "terminal_training_only_premise_rejected",
        "markets": ["BTC-USDT", "ETH-USDT"],
        "candidate_count": 0,
        "diagnostic_count": 1,
        "source_acquired": True,
        "training_diagnostic_evaluated": True,
        "candidate_performance_evaluated": False,
        "oos_accessed": False,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "c6ce3ecc0ee67ca0dd99f86c99866d32beff1c1a",
        "workflow_runs": {
            "python_package_build": 30636452953,
            "hourly_quant_research": 30636450681,
            "canonical_btc_eth_1h_research": 30636450879,
            "okx_1h_data_coverage": 30636450891,
        },
        "verdict": "reject_lag1_self_contained_b1_payoff_memory_premise",
        "markets_passing_all_gates": 0,
        "rejection_evidence": {
            "BTC-USDT": {
                "eligible_pairs": 85,
                "lag1_correlation": -0.0684,
                "sign_delta": 0.3159,
                "mean_payoff_delta": -0.008575,
                "positive_folds": 2,
                "complete_folds": 6,
                "positive_years": 1,
                "represented_years": 3,
                "positive_prior_state_count": 14,
            },
            "ETH-USDT": {
                "eligible_pairs": 85,
                "lag1_correlation": -0.0187,
                "sign_delta": 0.2396,
                "mean_payoff_delta": -0.010350,
                "positive_folds": 2,
                "complete_folds": 6,
                "positive_years": 1,
                "represented_years": 3,
                "positive_prior_state_count": 18,
            },
            "common_median_lag1_correlation": -0.0435,
            "common_median_sign_delta": 0.2778,
            "common_median_mean_payoff_delta": -0.009462,
        },
        "reason": (
            "bilateral lag-1 payoff correlations and conditional next-payoff magnitude deltas were negative, "
            "temporal breadth and minimum-state-count gates failed, and 0/2 markets passed all frozen gates"
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
        "do not rescue the rejected lag-1 payoff-memory premise; separately preregister a training-only "
        "trend-opportunity diagnostic using the preceding 168H fraction near the 2160H endpoint boundary "
        "to predict next-week B1 gross opportunity and adverse excursion before any executable candidate"
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
