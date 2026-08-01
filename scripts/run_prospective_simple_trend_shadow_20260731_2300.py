from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_2200 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_528_000_000  # 2026-07-31T20:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_531_600_000  # 2026-07-31T21:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_535_200_000  # 2026-07-31T22:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_538_800_000  # 2026-07-31T23:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_517_200_000  # 2026-07-31T17:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "f77af750c9cc9e7e51bc8ad57741063f5f18c352c56fa5fa73c640c199531191"
PRIOR_ARTIFACT_SHA256 = "c7c6346e2bf3565804949ad558ebe9f3170762d3cb9420311d99feab0e9a9118"


def configure_frozen_epoch() -> None:
    prior.PREVIOUS_DECISION_HOUR_MS = PREVIOUS_DECISION_HOUR_MS
    prior.REALIZED_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
    prior.PRIOR_REPORTED_SIGNAL_HOUR_MS = PRIOR_REPORTED_SIGNAL_HOUR_MS
    prior.LATEST_COMPLETE_SIGNAL_HOUR_MS = LATEST_COMPLETE_SIGNAL_HOUR_MS
    prior.RECENT_WINDOW_FIRST_DECISION_HOUR_MS = RECENT_WINDOW_FIRST_DECISION_HOUR_MS
    prior.RECENT_WINDOW_LAST_DECISION_HOUR_MS = RECENT_WINDOW_LAST_DECISION_HOUR_MS
    prior.PRIOR_RESULT_SHA256 = PRIOR_RESULT_SHA256
    prior.PRIOR_ARTIFACT_SHA256 = PRIOR_ARTIFACT_SHA256


def rewrite_report(output_dir: Path) -> None:
    report_path = output_dir / "report.md"
    lines: list[str] = []
    for line in report_path.read_text().splitlines():
        if line.startswith("# Prospective simple-trend shadow update through"):
            lines.append("# Prospective simple-trend shadow update through 23:00 UTC on 31 July 2026")
        else:
            lines.append(line)
    report = "\n".join(lines) + "\n"
    heading = "## Correction protocol\n"
    start = report.index(heading) + len(heading)
    end = report.index("\n## Abort conditions and verdict", start)
    correction = """

- Correction permitted: `False`
- Correction applied: `False`
- Policy changed: `false`
- Observation epoch restarted: `false`

Issue #833 and evidence PR #832 terminally reject the separately preregistered
`bocpd-duration-transition-ensemble-1h-v1` architecture. The sole zero-grid
candidate combined fixed duration-conditioned Beta-Bernoulli experts over the
complete causal BOCPD run-length posterior and was evaluated independently on
immutable BNBUSDT and VETUSDT public Binance SPOT 1H cohorts with exactly 5 bps
per one-way exposure change. BNB OOS net return was +41.9122% with Sharpe
+0.7056, but its paired candidate-minus-trend and candidate-minus-parent lower
mean-delta bounds remained below zero; it passed 11/12 gates. VET reversed from
+2.7917% training net to -28.7145% OOS net with Sharpe -0.5196, only 2/6 positive
folds and 1/2 positive years, negative delayed OOS return, and passed 3/12 gates.
Markets accepted were 0/2. The architecture improved binary calibration only
marginally and did not transport opportunity magnitude or persistence across
instruments. No duration-bin, prior, threshold, label-horizon, BOCPD parameter,
online-OOS update, or market-deletion rescue is authorised. The canonical
BTC/ETH 2,160H policy, chronology, fee model, and prospective epoch remain
immutable.
"""
    report_path.write_text(report[:start] + correction + report[end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 573
    result["window"]["updated_cumulative_realized_hours"] = 574
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 833,
        "pull_request": 832,
        "family_id": "bocpd-duration-transition-ensemble-1h-v1",
        "status": "terminal_architecture_rejected",
        "classification": "one_candidate_executable_temporal_architecture_experiment",
        "markets": ["BNBUSDT", "VETUSDT"],
        "candidate_count": 1,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "training_diagnostic_evaluated": True,
        "candidate_performance_evaluated": True,
        "oos_accessed": True,
        "later_data_accessed": True,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "255947db255574689e54d6f9b821675a0795693d",
        "workflow_run": 30674551718,
        "artifact_id": 8809983772,
        "artifact_sha256": "de692adf5fae863f6d3eedf7b0b99d32a77551f5d57f9d20f24ffaea2fe44e3e",
        "evidence_sha256": "6fc01ce40ebcbd25e4cf2d980aca5219a3762dbd6057519c7deb3d98701f4cc9",
        "verdict": "reject_bocpd_duration_transition_ensemble_architecture_v1",
        "markets_accepted": 0,
        "market_count": 2,
        "rejection_evidence": {
            "BNBUSDT": {
                "train_net_return": 0.49619680581780057,
                "oos_net_return": 0.41912236368691214,
                "oos_sharpe": 0.7055573972923295,
                "oos_max_drawdown": -0.35750712642756977,
                "oos_turnover": 52.0,
                "oos_fee_sum": 0.026,
                "oos_edge_per_turnover": 0.00806004545551754,
                "trend_oos_net_return": 0.12038785755317671,
                "parent_oos_net_return": -0.41115993886910884,
                "positive_folds": 4,
                "positive_years": 2,
                "gates_passed": 11,
                "gate_count": 12,
                "delayed_oos_net_return": 0.4885451378361425,
                "mean_delta_vs_trend_ci95_bps": [-0.31468552384083304, 0.8028024826739263],
                "mean_delta_vs_parent_ci95_bps": [-0.007507364802906925, 1.617968425178182],
            },
            "VETUSDT": {
                "train_net_return": 0.027917,
                "oos_net_return": -0.287145,
                "oos_sharpe": -0.5196,
                "oos_max_drawdown": -0.522613,
                "oos_turnover": 72.0,
                "oos_fee_sum": 0.036,
                "oos_edge_per_turnover": -0.003988,
                "trend_oos_net_return": 0.176613,
                "parent_oos_net_return": -0.267053,
                "positive_folds": 2,
                "positive_years": 1,
                "gates_passed": 3,
                "gate_count": 12,
                "delayed_oos_net_return": -0.080323,
                "mean_delta_vs_trend_ci95_bps": [-1.766434352650893, 0.4940142325320941],
                "mean_delta_vs_parent_ci95_bps": [-1.231792187623361, 0.8253841593980781],
            },
        },
        "reason": (
            "binary fee-clearing calibration improved marginally, but opportunity magnitude and persistence did not transport bilaterally; "
            "BNB uncertainty lower bounds failed and VET reversed to negative OOS economics"
        ),
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the duration-transition ensemble accepted zero of two markets; same-cohort duration-bin, prior, threshold, horizon, "
            "BOCPD-parameter, OOS-update, and market-subset rescue are closed"
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
        "do not rescue the rejected BOCPD duration-transition ensemble; separately preregister one fixed multi-horizon "
        "state-space trend ensemble on a fresh immutable cohort using causal 24H, 168H, and 720H filters, frozen training-only "
        "proper-score weights, and one turnover-cost-aware hysteretic long/cash rule"
    )
    base.write_outputs(output_dir, result)
    prior.write_report(output_dir, result)
    rewrite_report(output_dir)
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
