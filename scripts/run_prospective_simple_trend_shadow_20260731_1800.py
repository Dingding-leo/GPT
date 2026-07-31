from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_1700 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_510_000_000  # 2026-07-31T15:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_513_600_000  # 2026-07-31T16:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_517_200_000  # 2026-07-31T17:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_520_800_000  # 2026-07-31T18:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_499_200_000  # 2026-07-31T12:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "271a1012409adce48352541424863bef67491b21d9e46473cb8362791cd98c6e"
PRIOR_ARTIFACT_SHA256 = "183bf3c8765a3aa297a698faa631aead1887e3545810563d4db4764961b01311"


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
            lines.append("# Prospective simple-trend shadow update through 18:00 UTC on 31 July 2026")
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

Issue #814 and evidence PR #815 terminally reject the training-only
`coinm-basis-compression-resilience-opportunity-diagnostic-1h-v1` premise.
All 36 frozen Binance SPOT and COIN-M perpetual monthly archive/checksum pairs
were present and matched, producing 242 valid next-day observations per market.
The continuous basis-compression plus spot-resilience state failed bilateral
monotonic-information, dependence-aware lower-bound, and temporal-breadth gates.
BTC gross/adverse rank correlations were negative; ETH gross correlation was
approximately zero and adverse correlation was negative. Common-calendar 95%
intervals crossed zero for both endpoints, and zero of two markets passed every
gate. Candidate count and parameter grid were zero, no development OOS or
executable strategy performance was accessed, and the exactly 5 bps one-way fee
appeared only inside independent 24H target labels. No component reweighting,
threshold, lookback, date, source, or same-sample rescue is authorised. The
nominated BTC/ETH policy, chronology, fee model, scorecard, and observation
epoch remain immutable.
"""
    report_path.write_text(report[:correction_start] + correction + report[correction_end:])


def run(output_dir: Path, base_url: str) -> dict[str, Any]:
    configure_frozen_epoch()
    result = prior.run(output_dir, base_url)
    result["generated_at"] = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    result["elapsed_period_hours"] = 1
    result["new_public_observations_per_market"] = 1
    result["window"]["prior_cumulative_realized_hours"] = 568
    result["window"]["updated_cumulative_realized_hours"] = 569
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 814,
        "pull_request": 815,
        "family_id": "coinm-basis-compression-resilience-opportunity-diagnostic-1h-v1",
        "status": "terminal_training_only_information_premise_rejected",
        "markets": ["BTCUSDT", "ETHUSDT"],
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "source_contract_complete": True,
        "archive_checksum_pairs_verified": 36,
        "valid_decisions_per_market": 242,
        "training_diagnostic_evaluated": True,
        "candidate_performance_evaluated": False,
        "oos_accessed": False,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "cb1e3c400e3f0858a9ff3f9f9524c75cd5fc3ed2",
        "workflow_run": 30656840352,
        "artifact_id": 8803573112,
        "artifact_sha256": "94f4a5ecb2e8dd385a72f97073babd6efd3b470cf449d110f960a56a9498e477",
        "evidence_sha256": "49c24bb514baf79e12503c3b67529d0b06f343340df1964d076f7c07834cf980",
        "verdict": "reject_coinm_basis_compression_resilience_information_premise",
        "markets_passing_all_gates": 0,
        "rejection_evidence": {
            "BTCUSDT": {
                "gross_rank_correlation": -0.0497,
                "gross_rank_correlation_ci95": [-0.1493, 0.0432],
                "adverse_rank_correlation": -0.0731,
                "adverse_rank_correlation_ci95": [-0.1795, 0.0358],
                "positive_gross_folds": 3,
                "positive_adverse_folds": 3,
                "represented_folds": 8,
                "positive_gross_months": 3,
                "positive_adverse_months": 3,
                "represented_months": 8,
                "state_iqr": 1.3360,
                "mean_target_gross_return": 0.002173,
                "mean_target_net_return": 0.001173,
                "mean_target_adverse_excursion": -0.016433,
            },
            "ETHUSDT": {
                "gross_rank_correlation": 0.0020,
                "gross_rank_correlation_ci95": [-0.1031, 0.1051],
                "adverse_rank_correlation": -0.0171,
                "adverse_rank_correlation_ci95": [-0.1412, 0.1061],
                "positive_gross_folds": 6,
                "positive_adverse_folds": 4,
                "represented_folds": 8,
                "positive_gross_months": 6,
                "positive_adverse_months": 5,
                "represented_months": 8,
                "state_iqr": 1.6149,
                "mean_target_gross_return": 0.001193,
                "mean_target_net_return": 0.000193,
                "mean_target_adverse_excursion": -0.019967,
            },
            "common_calendar_gross_rank_correlation_ci95": [-0.1108, 0.0569],
            "common_calendar_adverse_rank_correlation_ci95": [-0.1432, 0.0541],
            "valid_bootstrap_draws": 5000,
        },
        "reason": (
            "the frozen basis-compression plus spot-resilience state lacked bilateral monotonic information, "
            "dependence-aware lower bounds, and temporal breadth; zero of two markets passed all gates"
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
        "do not rescue the rejected COIN-M basis-compression/resilience premise; the next materially orthogonal "
        "training-only diagnostic may preregister one same-instrument spot-versus-COIN-M taker-flow absorption state "
        "with zero threshold grid and no OOS or executable candidate unless bilateral information gates pass"
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
