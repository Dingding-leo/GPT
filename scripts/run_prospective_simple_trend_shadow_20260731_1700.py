from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import run_prospective_simple_trend_shadow_1800 as base
import run_prospective_simple_trend_shadow_20260731_1600 as prior

PREVIOUS_DECISION_HOUR_MS = 1_785_506_400_000  # 2026-07-31T14:00:00Z
REALIZED_DECISION_HOUR_MS = 1_785_510_000_000  # 2026-07-31T15:00:00Z
PRIOR_REPORTED_SIGNAL_HOUR_MS = 1_785_513_600_000  # 2026-07-31T16:00:00Z
LATEST_COMPLETE_SIGNAL_HOUR_MS = 1_785_517_200_000  # 2026-07-31T17:00:00Z
RECENT_WINDOW_FIRST_DECISION_HOUR_MS = 1_785_495_600_000  # 2026-07-31T11:00:00Z
RECENT_WINDOW_LAST_DECISION_HOUR_MS = REALIZED_DECISION_HOUR_MS
PRIOR_RESULT_SHA256 = "95c8b47490f7ce2515b82aeebb2c9dbceddaa11718ac99b6994529ccc7aa012f"
PRIOR_ARTIFACT_SHA256 = "b6c297cbffbf00d54877d132f1e02ee8bdf6f12633f5fc4231883d3ed24f6038"


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
            lines.append("# Prospective simple-trend shadow update through 17:00 UTC on 31 July 2026")
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

Issue #811 and evidence PR #812 terminate the training-only
`coinm-liquidation-exhaustion-opportunity-diagnostic-1h-v1` premise before
feature construction. The immutable public source contract requested 566
objects and verified 563 payload/checksum pairs, but preregistered BTCUSD_PERP
COIN-M liquidation snapshot checksum objects were unavailable for 1, 11, and
12 June 2024. Candidate count and parameter grid were zero, completed decisions
were zero, and no performance or OOS information was accessed. The exactly
5 bps one-way fee remained frozen but was never applied to a completed label.
No date shift, missing-day tolerance, imputation, alternate source, symbol
substitution, same-sample rescue, or executable correction is authorised. The
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
    result["window"]["prior_cumulative_realized_hours"] = 567
    result["window"]["updated_cumulative_realized_hours"] = 568
    result["nomination_status"] = "no_statistically_eligible_frozen_strategy"
    result["active_alpha_context"] = {
        "issue": 811,
        "pull_request": 812,
        "family_id": "coinm-liquidation-exhaustion-opportunity-diagnostic-1h-v1",
        "status": "terminal_training_only_source_contract_aborted",
        "markets": ["BTCUSDT", "ETHUSDT"],
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "source_contract_complete": False,
        "requested_source_objects": 566,
        "verified_source_objects": 563,
        "failed_source_objects": 3,
        "missing_periods": ["2024-06-01", "2024-06-11", "2024-06-12"],
        "training_diagnostic_evaluated": False,
        "candidate_performance_evaluated": False,
        "completed_decisions": 0,
        "oos_accessed": False,
        "prospective_performance_consumed": False,
        "correction_permitted": False,
        "tested_head": "abcd0b0e2a39355d125d526a62f2c0d4d4b67038",
        "workflow_run": 30654565927,
        "artifact_id": 8802712306,
        "artifact_sha256": "ef6f286652755ae9ca90fd7ef31410293e2bd48c27b9b6476d5e9e9041facc68",
        "verdict": "abort_fixed_source_contract_missing_public_objects",
        "markets_passing_all_gates": 0,
        "reason": (
            "three preregistered BTCUSD_PERP liquidation snapshot checksum objects were unavailable, "
            "so the immutable source contract aborted before feature, target, fee, or performance construction"
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
        "do not rescue the aborted COIN-M liquidation source contract; any distinct exogenous-data premise "
        "must be separately preregistered on a coverage-verified immutable public source"
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
