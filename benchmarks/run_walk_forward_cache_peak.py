#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import statistics
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import gpt_quant.walk_forward as walk_forward
import run_walk_forward_cache as cache_benchmark
from gpt_quant import load_price_csv

Workload = Callable[[], walk_forward.WalkForwardResult]
PeakResult = tuple[int, walk_forward.WalkForwardResult]


def _traced_peak_result(workload: Workload) -> PeakResult:
    gc.collect()
    tracemalloc.start()
    tracemalloc.reset_peak()
    try:
        result = workload()
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak_bytes, result


def _paired_peak_bytes(
    baseline: Workload,
    optimized: Workload,
    repetitions: int,
) -> tuple[int, int]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    baseline_samples: list[int] = []
    optimized_samples: list[int] = []
    for repetition in range(repetitions):
        if repetition % 2 == 0:
            baseline_peak, baseline_result = _traced_peak_result(baseline)
            optimized_peak, optimized_result = _traced_peak_result(optimized)
        else:
            optimized_peak, optimized_result = _traced_peak_result(optimized)
            baseline_peak, baseline_result = _traced_peak_result(baseline)
        cache_benchmark._assert_equal(baseline_result, optimized_result)
        baseline_samples.append(baseline_peak)
        optimized_samples.append(optimized_peak)
    return (
        int(statistics.median(baseline_samples)),
        int(statistics.median(optimized_samples)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure traced peak allocations for uncached and cached walk-forward research."
    )
    parser.add_argument("--csv", required=True)
    parser.add_argument("--config", default="config/okx_research.json")
    parser.add_argument("--repetitions", type=int, default=1)
    args = parser.parse_args()

    csv_path = Path(args.csv)
    prices = load_price_csv(csv_path)
    settings = cache_benchmark._settings(Path(args.config))

    def baseline() -> walk_forward.WalkForwardResult:
        return cache_benchmark._run_with_candidate_window(
            prices,
            settings,
            cache_benchmark._legacy_candidate_window,
        )

    def optimized() -> walk_forward.WalkForwardResult:
        return cache_benchmark._run_with_candidate_window(
            prices,
            settings,
            walk_forward._run_cached_candidate_window,
        )

    baseline_peak, optimized_peak = _paired_peak_bytes(
        baseline,
        optimized,
        args.repetitions,
    )
    increase = optimized_peak / baseline_peak - 1.0
    print(f"csv_sha256={cache_benchmark._sha256(csv_path)}")
    print(f"observations={len(prices)}")
    print("equivalence=exact")
    print(f"baseline_peak_traced_bytes={baseline_peak}")
    print(f"optimized_peak_traced_bytes={optimized_peak}")
    print(f"peak_traced_memory_increase_percent={increase * 100.0:.2f}")
    print(f"peak_traced_memory_ratio={optimized_peak / baseline_peak:.3f}x")


if __name__ == "__main__":
    main()
