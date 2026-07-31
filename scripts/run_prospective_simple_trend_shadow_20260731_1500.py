from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_1400 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_499_200_000  # 2026-07-31T12:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_502_800_000  # 2026-07-31T13:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_506_400_000  # 2026-07-31T14:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_510_000_000  # 2026-07-31T15:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_488_400_000  # 2026-07-31T09:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "9c4587ed74e40607489dfdc5af33db5855acd1a90a37b22a6de40e8d7e9cb9d3"
PRIOR_ARTIFACT_SHA256 = "beab02fa7deda6ab68c4d6fb43292b02508e8f2799b8c86bca5e69bd7e805146"


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
            lines.append("# Prospective simple-trend shadow update through 15:00 UTC on 31 July 2026")
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

Issue #803 and evidence PR #804 reject the training-only
`signed-path-coherence-opportunity-diagnostic-1h-v1` premise on canonical
BTC-USDT and ETH-USDT history. Candidate count and parameter grid were zero,
development OOS was unread, and no executable strategy was created. The
continuous state repaired the prior occupancy saturation, but bilateral
magnitude information did not survive: every dependence-aware lower bound
crossed zero, fold breadth was insufficient, BTC gross rank association was
effectively zero, ETH high-coherence weeks had worse adverse excursion, and
0/2 markets passed every frozen gate. Exact-head repository validation remains
an evidence-publication concern only and cannot authorize a same-sample rescue.
No horizon, denominator, conditioning rule, cadence, threshold, market
substitution, executable rule, or prospective correction is authorised. The
nominated BTC/ETH policy, fee model, chronology, scorecard, and observation
epoch remain immutable.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 565
    result["window"]["updated_cumulative_realized_hours"] = 566
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 803,
        "pull_request": 804,
        "family_id": "signed-path-coherence-opportunity-diagnostic-1h-v1",
        "status": "terminal_training_only_premise_rejected",
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
        "tested_head": "4611e9323fd9cefdd8a8e7057fba10f1464fecbb",
        "workflow_runs": {
            "python_package_build": 30645997341,
            "hourly_quant_research": 30645997339,
            "canonical_btc_eth_1h_research": 30645997385,
            "okx_1h_data_coverage": 30645997340,
        },
        "verdict": "reject_signed_path_coherence_opportunity_premise",
        "markets_passing_all_gates": 0,
        "rejection_evidence": {
            "BTC-USDT": {
                "active_anchors": 32,
                "gross_opportunity_rho": 0.007697947214076245,
                "gross_opportunity_rho_ci95": [-0.4333514219415604, 0.4226652203753112],
                "adverse_excursion_rho": 0.1158357771260997,
                "adverse_excursion_rho_ci95": [-0.3342625000552147, 0.5129153383829431],
                "state_iqr": 0.15672362740967205,
                "positive_gross_folds": 2,
                "positive_adverse_folds": 3,
                "low_partition_support": 16,
                "high_partition_support": 16,
                "valid_bootstrap_fraction": 0.9224,
            },
            "ETH-USDT": {
                "active_anchors": 39,
                "gross_opportunity_rho": 0.12044534412955467,
                "gross_opportunity_rho_ci95": [-0.2171403503970602, 0.4737526888205199],
                "adverse_excursion_rho": 0.08582995951417005,
                "adverse_excursion_rho_ci95": [-0.262753990846171, 0.42383133518554456],
                "adverse_slope_per_state_sd": -0.0005599925301664802,
                "state_iqr": 0.12432363850011462,
                "positive_gross_folds": 2,
                "positive_adverse_folds": 2,
                "low_partition_support": 20,
                "high_partition_support": 19,
                "valid_bootstrap_fraction": 0.9924,
            },
            "common_median_gross_rho": 0.06407164567181546,
            "common_median_gross_rho_ci95": [-0.2966431555035584, 0.41894584959908815],
            "common_median_adverse_rho": 0.10083286832013488,
            "common_median_adverse_rho_ci95": [-0.24474803098095743, 0.43594053076398487],
            "common_valid_bootstrap_fraction": 0.9224,
        },
        "reason": (
            "continuous state dispersion improved, but uncertainty, fold breadth, partition support, "
            "and bilateral economic ordering failed; 0/2 markets passed all frozen gates"
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
        "do not rescue the rejected signed path-coherence premise; any distinct candidate must be separately "
        "preregistered, materially orthogonal, and evaluated on an availability-verified untouched cohort"
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
