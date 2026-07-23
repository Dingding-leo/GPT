#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from collections.abc import Callable, Iterable, Mapping
from itertools import chain
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig, load_price_csv

CandidateCache = dict[StrategyConfig, pd.DataFrame]
CandidateWindow = Callable[
    [
        pd.Series,
        pd.Series,
        CandidateCache,
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


def _root_array(values: np.ndarray) -> np.ndarray:
    root = values
    while isinstance(root.base, np.ndarray):
        root = root.base
    return root


def _unique_root_array_bytes(arrays: Iterable[np.ndarray]) -> int:
    """Count each retained NumPy root buffer exactly once."""

    buffers: dict[int, np.ndarray] = {}
    for values in arrays:
        root = _root_array(values)
        buffers.setdefault(id(root), root)
    return sum(int(root.nbytes) for root in buffers.values())


def _cache_column_arrays(cache: Mapping[StrategyConfig, pd.DataFrame]) -> Iterable[np.ndarray]:
    for frame in cache.values():
        for _, column in frame.items():
            yield column.to_numpy(copy=False)


def _cache_index_arrays(cache: Mapping[StrategyConfig, pd.DataFrame]) -> Iterable[np.ndarray]:
    for frame in cache.values():
        if not isinstance(frame.index, pd.DatetimeIndex):
            raise TypeError("candidate cache index must be a DatetimeIndex")
        yield frame.index.asi8


def _cache_column_bytes(cache: Mapping[StrategyConfig, pd.DataFrame]) -> int:
    """Count each retained candidate-column root buffer exactly once."""

    return _unique_root_array_bytes(_cache_column_arrays(cache))


def _cache_unique_index_bytes(cache: Mapping[StrategyConfig, pd.DataFrame]) -> int:
    """Count each retained DatetimeIndex root buffer exactly once."""

    return _unique_root_array_bytes(_cache_index_arrays(cache))


def _cache_retained_array_bytes(cache: Mapping[StrategyConfig, pd.DataFrame]) -> int:
    """Count each retained column or index root buffer exactly once."""

    return _unique_root_array_bytes(
        chain(_cache_column_arrays(cache), _cache_index_arrays(cache))
    )


def _legacy_candidate_window(
    point_in_time_history: pd.Series,
    complete_history: pd.Series,
    cache: CandidateCache,
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


def _full_frame_cached_candidate_window(
    point_in_time_history: pd.Series,
    complete_history: pd.Series,
    cache: CandidateCache,
    config: StrategyConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    previous_position: float,
) -> pd.DataFrame:
    """Reference the cache layout before rebuilt NAV was removed."""

    del point_in_time_history
    template = cache.get(config)
    if template is None:
        template = walk_forward.run_backtest(complete_history, config).frame
        cache[config] = template
    return walk_forward._rebase_test_window(
        template.loc[start:end],
        config,
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
    optimized_cache: CandidateCache | None = None
    latest_optimized_result: walk_forward.WalkForwardResult | None = None
    optimized_helper = walk_forward._run_cached_candidate_window

    def baseline() -> walk_forward.WalkForwardResult:
        return _run_with_candidate_window(prices, settings, _legacy_candidate_window)

    def capture_optimized_cache(
        point_in_time_history: pd.Series,
        complete_history: pd.Series,
        cache: CandidateCache,
        config: StrategyConfig,
        start: pd.Timestamp,
        end: pd.Timestamp,
        previous_position: float,
    ) -> pd.DataFrame:
        nonlocal optimized_cache
        optimized_cache = cache
        return optimized_helper(
            point_in_time_history,
            complete_history,
            cache,
            config,
            start,
            end,
            previous_position,
        )

    def optimized() -> walk_forward.WalkForwardResult:
        nonlocal latest_optimized_result
        latest_optimized_result = _run_with_candidate_window(
            prices,
            settings,
            capture_optimized_cache,
        )
        return latest_optimized_result

    baseline_median, optimized_median = _paired_medians(
        baseline,
        optimized,
        args.repetitions,
    )
    if optimized_cache is None or latest_optimized_result is None:
        raise RuntimeError("optimized benchmark did not populate the candidate cache")

    full_frame_cache: CandidateCache | None = None

    def capture_full_frame_cache(
        point_in_time_history: pd.Series,
        complete_history: pd.Series,
        cache: CandidateCache,
        config: StrategyConfig,
        start: pd.Timestamp,
        end: pd.Timestamp,
        previous_position: float,
    ) -> pd.DataFrame:
        nonlocal full_frame_cache
        full_frame_cache = cache
        return _full_frame_cached_candidate_window(
            point_in_time_history,
            complete_history,
            cache,
            config,
            start,
            end,
            previous_position,
        )

    full_frame_result = _run_with_candidate_window(
        prices,
        settings,
        capture_full_frame_cache,
    )
    if full_frame_cache is None:
        raise RuntimeError("full-frame benchmark did not populate the candidate cache")
    _assert_equal(full_frame_result, latest_optimized_result)

    full_frame_column_bytes = _cache_column_bytes(full_frame_cache)
    optimized_column_bytes = _cache_column_bytes(optimized_cache)
    full_frame_index_bytes = _cache_unique_index_bytes(full_frame_cache)
    optimized_index_bytes = _cache_unique_index_bytes(optimized_cache)
    full_frame_retained_bytes = _cache_retained_array_bytes(full_frame_cache)
    optimized_retained_bytes = _cache_retained_array_bytes(optimized_cache)
    if full_frame_column_bytes <= optimized_column_bytes:
        raise AssertionError("optimized cache did not reduce retained candidate columns")
    if full_frame_index_bytes != optimized_index_bytes:
        raise AssertionError("cache layouts retained different index buffers")

    reduction = 1.0 - optimized_median / baseline_median
    column_reduction = 1.0 - optimized_column_bytes / full_frame_column_bytes
    retained_reduction = 1.0 - optimized_retained_bytes / full_frame_retained_bytes
    print(f"csv_sha256={_sha256(csv_path)}")
    print(f"observations={len(prices)}")
    print("equivalence=exact")
    print(f"baseline_median_seconds={baseline_median:.9f}")
    print(f"optimized_median_seconds={optimized_median:.9f}")
    print(f"reduction_percent={reduction * 100.0:.2f}")
    print(f"speedup={baseline_median / optimized_median:.3f}x")
    print(f"cache_entries={len(optimized_cache)}")
    print(f"full_frame_cache_column_bytes={full_frame_column_bytes}")
    print(f"optimized_cache_column_bytes={optimized_column_bytes}")
    print(f"cache_column_reduction_percent={column_reduction * 100.0:.2f}")
    print(f"cache_unique_index_bytes={optimized_index_bytes}")
    print(f"full_frame_cache_retained_array_bytes={full_frame_retained_bytes}")
    print(f"optimized_cache_retained_array_bytes={optimized_retained_bytes}")
    print(f"cache_retained_array_reduction_percent={retained_reduction * 100.0:.2f}")


if __name__ == "__main__":
    main()
