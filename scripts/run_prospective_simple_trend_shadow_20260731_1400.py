from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_1300 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_495_600_000  # 2026-07-31T11:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_499_200_000  # 2026-07-31T12:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_502_800_000  # 2026-07-31T13:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_506_400_000  # 2026-07-31T14:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_484_800_000  # 2026-07-31T08:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "f371574ef9e1e7eccdec2e61b806156b02fed79780b0ee99440c04f156287ffc"
PRIOR_ARTIFACT_SHA256 = "46535939f644ca596a6ba0826641b058f9e43b0f56ef3dfb850d46c55fc466e8"


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
            lines.append("# Prospective simple-trend shadow update through 14:00 UTC on 31 July 2026")
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

Issue #798 and evidence PR #799 terminally reject the training-only
`trend-boundary-occupancy-opportunity-diagnostic-1h-v1` premise on canonical
BTC-USDT and ETH-USDT data. Candidate count was zero and development OOS was
unread. Point correlations between boundary clearance and subsequent B1 gross
opportunity or adverse excursion were positive, but every dependence-aware
interval crossed zero, fold/year signs lacked breadth, and the preregistered
state-variation and half-ordering gates failed. Median occupancy was zero in
both markets and many future sleeves remained inactive, so the apparent
relationship was partly a persistent-cash-state effect. Markets passing every
gate were 0/2. No threshold, smoothing, alternate normalisation, binary-presence
rescue, market substitution, executable rule, or prospective correction is
authorised. The nominated BTC/ETH policy, fee model, chronology, scorecard, and
observation epoch remain immutable.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 564
    result["window"]["updated_cumulative_realized_hours"] = 565
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 798,
        "pull_request": 799,
        "family_id": "trend-boundary-occupancy-opportunity-diagnostic-1h-v1",
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
        "tested_head": "d574491e00913fe56288f25ab47357eeeebe5ec4",
        "workflow_runs": {
            "python_package_build": 30642194416,
            "hourly_quant_research": 30642194379,
            "canonical_btc_eth_1h_research": 30642194501,
            "okx_1h_data_coverage": 30642194270,
        },
        "verdict": "reject_trend_boundary_occupancy_opportunity_premise",
        "markets_passing_all_gates": 0,
        "rejection_evidence": {
            "BTC-USDT": {
                "gross_opportunity_rho": 0.16119260156983245,
                "gross_opportunity_rho_ci95": [-0.15768966929700995, 0.4504887847132558],
                "adverse_excursion_rho": 0.2255549911722802,
                "adverse_excursion_rho_ci95": [-0.08108299768418074, 0.5126160201690411],
                "occupancy_iqr": 0.03869047619047619,
                "positive_gross_folds": 1,
                "positive_gross_years": 1,
                "positive_adverse_folds": 3,
                "positive_adverse_years": 1,
                "zero_gross_weeks": 45,
            },
            "ETH-USDT": {
                "gross_opportunity_rho": 0.11433175928748086,
                "gross_opportunity_rho_ci95": [-0.11629157137435187, 0.33219276956105626],
                "adverse_excursion_rho": 0.10164066820134983,
                "adverse_excursion_rho_ci95": [-0.1503745896123925, 0.384534422197455],
                "occupancy_iqr": 0.23065476190476192,
                "positive_gross_folds": 2,
                "positive_gross_years": 2,
                "positive_adverse_folds": 2,
                "positive_adverse_years": 1,
                "zero_gross_weeks": 42,
            },
            "common_median_gross_rho": 0.13776218042865665,
            "common_median_gross_rho_ci95": [-0.12057750296398875, 0.38129032085693804],
            "common_median_adverse_rho": 0.16359782968681502,
            "common_median_adverse_rho_ci95": [-0.084594118397178, 0.4221728328698779],
        },
        "reason": (
            "all dependence-aware intervals crossed zero, temporal breadth and state-variation gates failed, "
            "the state was strongly zero-inflated, and 0/2 markets passed all frozen gates"
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
        "do not rescue the rejected boundary-occupancy premise; any distinct candidate must use a separately "
        "preregistered state construction on an availability-verified untouched cohort after a rejected-family overlap audit"
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
