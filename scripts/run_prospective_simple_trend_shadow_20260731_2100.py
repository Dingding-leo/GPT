from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_2000 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_520_800_000  # 2026-07-31T18:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_524_400_000  # 2026-07-31T19:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_528_000_000  # 2026-07-31T20:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_531_600_000  # 2026-07-31T21:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_510_000_000  # 2026-07-31T15:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "b17c72c9085e6ddaa1347d36e1030dd64e51c23d8de98117801d02e970eec5bf"
PRIOR_ARTIFACT_SHA256 = "f35c7123ec641910766bec7e2a799d8ed983be097a2db7fcdfb0fde67f62af3e"


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
            lines.append("# Prospective simple-trend shadow update through 21:00 UTC on 31 July 2026")
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

Issue #825 and evidence PR #826 terminally reject the retrospective
`scalar-state-family-closure-meta-analysis-1h-v1` architecture family. Seven
completed zero-grid scalar-state diagnostics contributed 14 paired BTC/ETH
market effects, collapsed into five independent information groups before
inference so three related B1-geometry variants could not outvote independent
channels. The grouped BTC median rank effect was -0.0076 with 95% family-cluster
interval [-0.0684,+0.0589]; ETH was +0.0020 with interval
[-0.0187,+0.1049]; the median bilateral group effect was -0.00705 with interval
[-0.04355,+0.08190]. Only 2/5 groups were positive in both markets, none of the
14 source lower confidence bounds exceeded zero, the minimum leave-one-group-out
bilateral median was -0.01545, and the exact one-sided sign-test p-value was
0.8125. All eight frozen acceptance gates failed. Candidate count and parameter
grid were zero, no new market performance or OOS observation was consumed, and
no scalar overlay, family removal, reweighting, threshold rescue, sign reversal,
or horizon subset is authorised. The sole permitted next research direction is
a separately preregistered structurally different Bayesian online change-point
long/cash architecture on a fresh immutable 1H cohort; it is not a correction to
this frozen prospective epoch. The nominated BTC/ETH policy, chronology, fee
model, and scorecard therefore remain immutable.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 571
    result["window"]["updated_cumulative_realized_hours"] = 572
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 825,
        "pull_request": 826,
        "family_id": "scalar-state-family-closure-meta-analysis-1h-v1",
        "status": "terminal_architecture_family_rejected",
        "classification": "retrospective_architecture_family_closure",
        "markets": ["BTC", "ETH"],
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "source_diagnostic_count": 7,
        "source_market_effect_count": 14,
        "independent_information_group_count": 5,
        "training_diagnostic_evaluated": True,
        "new_market_performance_evaluated": False,
        "candidate_performance_evaluated": False,
        "oos_accessed": False,
        "later_data_accessed": False,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "b3095b7aa6808665128b0b31901d4f1ee38a22c1",
        "workflow_run": 30668160800,
        "artifact_id": 8807759398,
        "artifact_sha256": "7a7a4cb6ba403125fbde0db8fb3e9f6b9516cb6f28cde3daa65d4fd5ed0bb3f6",
        "evidence_sha256": "437f5b81e24ad085d01447581301357b48235cb32de4f3fd1d981115e9179e87",
        "verdict": "reject_scalar_state_gating_architecture_family",
        "frozen_gates_passed": 0,
        "frozen_gate_count": 8,
        "rejection_evidence": {
            "bilateral_positive_diagnostics": 4,
            "source_diagnostic_count": 7,
            "bilateral_positive_groups": 2,
            "independent_group_count": 5,
            "positive_source_lower_bounds": 0,
            "source_market_effect_count": 14,
            "BTC_grouped_median_rank_correlation": -0.0076,
            "BTC_family_cluster_ci95": [-0.0684, 0.0589],
            "ETH_grouped_median_rank_correlation": 0.0020,
            "ETH_family_cluster_ci95": [-0.0187, 0.1049],
            "median_bilateral_group_effect": -0.00705,
            "bilateral_family_cluster_ci95": [-0.04355, 0.08190],
            "minimum_leave_one_group_out_bilateral_median": -0.01545,
            "one_sided_exact_sign_test_p": 0.8125,
            "bootstrap_resamples": 100000,
            "bootstrap_seed": 20260801,
        },
        "reason": (
            "independent family clustering removed the apparent advantage from repeated B1-geometry variants; "
            "the grouped bilateral median was negative and every frozen breadth, uncertainty, robustness, and sign gate failed"
        ),
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the scalar-state architecture family was rejected and the authorised Bayesian change-point research direction "
            "requires a separate preregistration and fresh observation contract rather than mutation of this epoch"
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
        "terminate further scalar-state gating; separately preregister one fixed Bayesian online change-point "
        "long/cash architecture on a fresh immutable 1H cohort with a frozen likelihood, hazard, prior, hysteretic "
        "turnover-aware rule, next-open execution, and exactly 5 bps one way before any performance access"
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
