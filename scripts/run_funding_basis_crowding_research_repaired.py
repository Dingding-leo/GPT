#!/usr/bin/env python3
"""Run the frozen funding/basis diagnostic with complete qualification screens.

This wrapper does not alter F0/F1 signals, data, timing, costs, folds, bootstrap,
or candidate accounting. It repairs the published strategy verdict by enforcing
the predeclared profitable-fold breadth and positive-fold concentration gates,
and adds risk/capacity diagnostics derived from the unchanged hourly paths.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

import run_funding_basis_crowding_research as base

_ORIGINAL_METRICS = base.metrics


def _capacity_diagnostics(
    annualized_turnover: float,
    max_hourly_adjustment: float,
) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for notional in (10_000.0, 100_000.0, 1_000_000.0):
        key = f"usd_{int(notional)}"
        result[key] = {
            "annual_adjusted_notional": annualized_turnover * notional,
            "annual_modeled_fee": annualized_turnover * notional * base.FEE,
            "max_one_hour_adjustment": max_hourly_adjustment * notional,
        }
    return result


def repaired_metrics(frame, policy: str, fold_ids: np.ndarray) -> dict[str, Any]:  # noqa: ANN001
    result = _ORIGINAL_METRICS(frame, policy, fold_ids)
    returns = frame[f"net_return_{policy}"].to_numpy(dtype=float)
    turnover = frame[f"turnover_{policy}"].to_numpy(dtype=float)
    downside = np.minimum(returns, 0.0)
    annualized_downside_semivolatility = float(
        math.sqrt(float(np.mean(np.square(downside)))) * math.sqrt(base.YEAR_HOURS)
    )
    max_hourly_adjustment = float(np.max(turnover)) if len(turnover) else 0.0
    result.update(
        {
            "annualized_downside_semivolatility": annualized_downside_semivolatility,
            "max_hourly_adjustment": max_hourly_adjustment,
            "capacity_diagnostics": _capacity_diagnostics(
                float(result["annualized_turnover"]),
                max_hourly_adjustment,
            ),
        }
    )
    return result


def enforce_complete_screens(result: dict[str, Any]) -> dict[str, Any]:
    failures = set(str(item) for item in result.get("deterministic_failures", []))
    for market, market_metrics in result["metrics"].items():
        f1 = market_metrics["f1"]
        total_folds = int(f1["total_folds"])
        minimum_profitable_folds = math.ceil(total_folds / 2)
        concentration = f1["positive_fold_concentration"]
        breadth_pass = int(f1["profitable_folds"]) >= minimum_profitable_folds
        concentration_pass = concentration is not None and float(concentration) <= 0.5
        screens = result["markets"][market]["deterministic_screens"]
        screens["profitable_fold_breadth"] = breadth_pass
        screens["positive_fold_concentration_at_most_half"] = concentration_pass
        if not breadth_pass:
            failures.add(f"{market}:profitable_fold_breadth")
        if not concentration_pass:
            failures.add(f"{market}:positive_fold_concentration_at_most_half")

    result["deterministic_failures"] = sorted(failures)
    result["methodological_repair"] = {
        "name": "complete_predeclared_fold_qualification_screens",
        "strategy_paths_changed": False,
        "data_or_sample_changed": False,
        "candidate_budget_changed": False,
        "fee_or_timing_changed": False,
        "added_screens": [
            "at least half of short-window folds profitable",
            "no single fold contributes more than 50% of positive fold return",
        ],
    }
    if failures:
        result["verdict"] = "rejected_by_predeclared_short_window_diagnostic"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    base.metrics = repaired_metrics
    result = enforce_complete_screens(base.run(args.output_dir))
    result_bytes = base.canonical_bytes(base.finite(result))
    (args.output_dir / "result-summary.json").write_bytes(result_bytes)
    (args.output_dir / "result-summary.sha256").write_text(
        f"{base.sha256(result_bytes)}  result-summary.json\n",
        encoding="utf-8",
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
