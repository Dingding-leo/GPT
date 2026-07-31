from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_2100 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_524_400_000  # 2026-07-31T19:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_528_000_000  # 2026-07-31T20:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_531_600_000  # 2026-07-31T21:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_535_200_000  # 2026-07-31T22:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_513_600_000  # 2026-07-31T16:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "9831dbed2ec327f5f27d6dc93b044ad1e4c64e0c3842153db7b128e46ac5270a"
PRIOR_ARTIFACT_SHA256 = "be8b3e552ffca59e75b8322bab7bf0d44827c0948a120ee908b79e1578df9c99"


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
            lines.append("# Prospective simple-trend shadow update through 22:00 UTC on 31 July 2026")
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

Issue #828 and evidence PR #829 terminally reject the separately preregistered
`bocpd-runlength-hysteresis-1h-v1` architecture. The sole candidate retained the
full capped causal BOCPD run-length posterior and used one frozen posterior-mixture
entry/exit rule with a 24-hour minimum hold, next-open execution, and exactly 5
bps per one-way transition. It was profitable in training but reversed in the
later development-OOS cohort: BTC OOS net return was -13.7036% with Sharpe
-0.3000 versus canonical trend -6.5561% / -0.0730; ETH OOS net return was
-34.1476% with Sharpe -0.5187 versus trend -12.3843% / -0.0104. OOS gross return
was already negative in both instruments, turnover was 152/182 one-way units,
fee drag was 7.60%/9.10%, only 2/6 folds and 0/2 calendar years were positive,
and one-hour delayed OOS returns fell to -18.9124%/-44.0241%. Dependence-aware
candidate-minus-trend confidence intervals crossed zero in both markets. Only
the bounded-turnover and positive-full-sample gates passed; every OOS return,
benchmark, drawdown, edge-per-turnover, breadth, uncertainty, and delay gate
failed bilaterally. No threshold, hazard, prior, run-cap, hold-period, market
subset, or OOS-dependent rescue is authorised. The canonical BTC/ETH 2,160H
policy, chronology, fee model, and forward scorecard remain immutable.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 572
    result["window"]["updated_cumulative_realized_hours"] = 573
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 828,
        "pull_request": 829,
        "family_id": "bocpd-runlength-hysteresis-1h-v1",
        "status": "terminal_architecture_rejected",
        "classification": "one_candidate_executable_temporal_architecture_experiment",
        "markets": ["BTC-USDT", "ETH-USDT"],
        "candidate_count": 1,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "training_diagnostic_evaluated": True,
        "candidate_performance_evaluated": True,
        "oos_accessed": True,
        "later_data_accessed": True,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "49c53c009443842c3143675ffa09d5d48624d9ba",
        "workflow_run": 30672271028,
        "artifact_id": 8809213000,
        "artifact_sha256": "ffcad976d2414f13e902147e7f334a25e7c4705c7643de88f5c7b4126ce34a9c",
        "evidence_sha256": "be01bc46b48e5eee24fe1fd4afade554fb14ebe02205ae20f90694a1f5f7b26e",
        "verdict": "reject_bocpd_runlength_hysteresis_architecture_v1",
        "frozen_gates_passed_per_market": 2,
        "frozen_gate_count": 10,
        "rejection_evidence": {
            "BTC_USDT": {
                "train_net_return": 0.6772778989152508,
                "train_sharpe": 1.3619183170370328,
                "oos_gross_return": -0.06886254898676392,
                "oos_net_return": -0.1370364147937343,
                "oos_sharpe": -0.30002782619687635,
                "oos_max_drawdown": -0.29511601826033707,
                "oos_turnover": 152.0,
                "oos_fee_sum": 0.076,
                "oos_edge_per_turnover": -0.0009015553604850941,
                "trend_oos_net_return": -0.06556128319321897,
                "trend_oos_sharpe": -0.07303549866632461,
                "positive_folds": 2,
                "fold_count": 6,
                "positive_years": 0,
                "year_count": 2,
                "delayed_oos_net_return": -0.18912372888252116,
                "full_net_return": 0.4474297490351271,
                "mean_net_delta_ci95": [-0.00004203684323169861, 0.00004023059154419137],
            },
            "ETH_USDT": {
                "train_net_return": 0.673360,
                "train_sharpe": 1.2136,
                "oos_gross_return": -0.278774,
                "oos_net_return": -0.341476,
                "oos_sharpe": -0.5187,
                "oos_max_drawdown": -0.483842,
                "oos_turnover": 182.0,
                "oos_fee_sum": 0.091,
                "oos_edge_per_turnover": -0.001876,
                "trend_oos_net_return": -0.123843,
                "trend_oos_sharpe": -0.0104,
                "positive_folds": 2,
                "fold_count": 6,
                "positive_years": 0,
                "year_count": 2,
                "delayed_oos_net_return": -0.440241,
                "full_net_return": 0.101948,
                "mean_net_delta_ci95": [-0.00009563, 0.00006232],
            },
        },
        "reason": (
            "the posterior-hysteresis rule reversed from profitable training performance to negative gross and net OOS returns in both markets, "
            "underperformed the canonical trend benchmark, lacked temporal breadth, and failed dependence-aware and delay robustness gates"
        ),
    }
    result["training_authorized_correction"] = {
        "permitted": False,
        "applied": False,
        "policy_changed": False,
        "observation_epoch_restarted": False,
        "reason": (
            "the fixed BOCPD architecture failed eight of ten preregistered gates in both markets; any duration-conditioned transition ensemble "
            "must be separately preregistered and evaluated on a fresh immutable cohort rather than mutate this prospective epoch"
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
        "do not rescue the rejected BOCPD posterior-hysteresis rule; separately preregister one fixed duration-conditioned "
        "transition ensemble trained only on permitted history with a proper scoring rule and evaluate it once on a fresh immutable 1H cohort"
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
