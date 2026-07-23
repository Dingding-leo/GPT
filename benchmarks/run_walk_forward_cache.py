#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig, load_price_csv

CandidateWindow = Callable[
    [
        pd.Series,
        pd.Series,
        dict[StrategyConfig, pd.DataFrame],
        StrategyConfig,
        pd.Timestamp,
        pd.Timestamp,
        float,
    ],
    pd.DataFrame,
]
Workload = Callable[[], walk_forward.WalkForwardResult]
TimedResult = tuple[float, walk_forward.WalkForwardResult]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _settings(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        "base_config": StrategyConfig(**payload["strategy"]),
        "momentum_lookbacks": payload["search"]["momentum_lookbacks"],
        "reversal_lookbacks": payload["search"]["reversal_lookbacks"],
        "trend_weights": payload["search"]["trend_weights"],
        "selection_bars": payload["search"]["selection_bars"],
        "test_bars": payload["search"]["test_bars"],
        "cost_multipliers": payload["robustness"]["cost_multipliers"],
    }


def _legacy_candidate_window(
    point_in_time_history: pd.Series,
    complete_history: pd.Series,
    cache: dict[StrategyConfig, pd.DataFrame],
    config: StrategyConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    previous_position: float,
) -> pd.DataFrame:
    del complete_history, cache
    return walk_forward._run_test_window(
        point_in_time_history,
        config,
        start,
        end,
        previous_position,
    )


def _run_with_candidate_window(
    prices: pd.Series,
    settings: Mapping[str, Any],
    helper: CandidateWindow,
) -> walk_forward.WalkForwardResult:
    original = walk_forward._run_cached_candidate_window
    walk_forward._run_cached_candidate_window = helper
    try:
        return walk_forward.run_walk_forward_research(prices, **settings)
    finally:
        walk_forward._run_cached_candidate_window = original


def _assert_equal(
    baseline: walk_forward.WalkForwardResult,
    optimized: walk_forward.WalkForwardResult,
) -> None:
    baseline_payload = baseline.to_dict()
    optimized_payload = optimized.to_dict()
    baseline_payload.pop("generated_at_utc")
    optimized_payload.pop("generated_at_utc")
    if baseline_payload != optimized_payload:
        raise AssertionError("cached candidate path changed the public walk-forward payload")
    pd.testing.assert_frame_equal(
        baseline.combined_frame,
        optimized.combined_frame,
        check_exact=True,
    )
    for name in baseline.benchmark_frames:
        pd.testing.assert_frame_equal(
            baseline.benchmark_frames[name],
            optimized.benchmark_frames[name],
            check_exact=True,
        )
    for name in baseline.perturbation_frames:
        pd.testing.assert_frame_equal(
            baseline.perturbation_frames[name],
            optimized.perturbation_frames[name],
            check_exact=True,
        )


def _timed_result(workload: Workload) -> TimedResult:
    started = time.perf_counter()
    result = workload()
    return time.perf_counter() - started, result


def _paired_medians(
    baseline: Workload,
    optimized: Workload,
    repetitions: int,
) -> tuple[float, float]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    baseline_samples: list[float] = []
    optimized_samples: list[float] = []
    for repetition in range(repetitions):
        if repetition % 2 == 0:
            baseline_elapsed, baseline_result = _timed_result(baseline)
            optimized_elapsed, optimized_result = _timed_result(optimized)
        else:
            optimized_elapsed, optimized_result = _timed_result(optimized)
            baseline_elapsed, baseline_result = _timed_result(baseline)
        if repetition == 0:
            _assert_equal(baseline_result, optimized_result)
        baseline_samples.append(baseline_elapsed)
        optimized_samples.append(optimized_elapsed)
    return statistics.median(baseline_samples), statistics.median(optimized_samples)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Benchmark candidate-backtest reuse on an explicit real-market CSV."
    )
    parser.add_argument("--csv", required=True)
    parser.add_argument("--config", default="config/okx_research.json")
    parser.add_argument("--repetitions", type=int, default=3)
    args = parser.parse_args()
    if args.repetitions < 1:
        raise ValueError("repetitions must be positive")

    csv_path = Path(args.csv)
    prices = load_price_csv(csv_path)
    settings = _settings(Path(args.config))

    def baseline() -> walk_forward.WalkForwardResult:
        return _run_with_candidate_window(prices, settings, _legacy_candidate_window)

    def optimized() -> walk_forward.WalkForwardResult:
        return _run_with_candidate_window(
            prices,
            settings,
            walk_forward._run_cached_candidate_window,
        )

    baseline_median, optimized_median = _paired_medians(
        baseline,
        optimized,
        args.repetitions,
    )
    reduction = 1.0 - optimized_median / baseline_median
    print(f"csv_sha256={_sha256(csv_path)}")
    print(f"observations={len(prices)}")
    print("equivalence=exact")
    print(f"baseline_median_seconds={baseline_median:.9f}")
    print(f"optimized_median_seconds={optimized_median:.9f}")
    print(f"reduction_percent={reduction * 100.0:.2f}")
    print(f"speedup={baseline_median / optimized_median:.3f}x")


if __name__ == "__main__":
    main()
