#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pickle
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, NamedTuple

import pandas as pd
import run_walk_forward_cache as cache_benchmark

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig, load_price_csv

_EXTRA_MOMENTUM_LOOKBACK = 240
_EXTRA_REVERSAL_LOOKBACK = 15
_EXTRA_TREND_WEIGHT = 0.95


class ScalingMeasurement(NamedTuple):
    axis_size: int
    candidate_count: int
    elapsed_seconds: float
    peak_rss_bytes: int
    workload_peak_rss_increment_bytes: int
    cache_entries: int
    result: walk_forward.WalkForwardResult


class ScalingMedian(NamedTuple):
    axis_size: int
    candidate_count: int
    median_seconds: float
    median_peak_rss_bytes: int
    median_workload_peak_rss_increment_bytes: int
    median_cache_entries: int


def _normalize_peak_rss_bytes(raw_peak: int, platform: str) -> int:
    if raw_peak < 0:
        raise ValueError("peak RSS must be non-negative")
    return raw_peak if platform == "darwin" else raw_peak * 1024


def _peak_rss_bytes() -> int:
    try:
        import resource
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only off Unix
        raise RuntimeError("cache scaling benchmark requires the Unix resource module") from exc
    return _normalize_peak_rss_bytes(
        int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
        sys.platform,
    )


def _axis_values(
    settings: Mapping[str, Any],
    axis_size: int,
) -> tuple[list[int], list[int], list[float]]:
    if axis_size < 1 or axis_size > 4:
        raise ValueError("axis_size must be between 1 and 4")
    momentum = list(settings["momentum_lookbacks"])
    reversal = list(settings["reversal_lookbacks"])
    weights = list(settings["trend_weights"])
    if not (len(momentum) == len(reversal) == len(weights) == 3):
        raise ValueError("cache scaling benchmark requires three-value default search axes")
    momentum.append(_EXTRA_MOMENTUM_LOOKBACK)
    reversal.append(_EXTRA_REVERSAL_LOOKBACK)
    weights.append(_EXTRA_TREND_WEIGHT)
    if len(set(momentum)) != 4 or len(set(reversal)) != 4 or len(set(weights)) != 4:
        raise ValueError("cache scaling axis extensions must be distinct")
    return momentum[:axis_size], reversal[:axis_size], weights[:axis_size]


def _scaling_settings(config_path: Path, axis_size: int) -> dict[str, Any]:
    settings = cache_benchmark._settings(config_path)
    momentum, reversal, weights = _axis_values(settings, axis_size)
    return {
        **settings,
        "momentum_lookbacks": momentum,
        "reversal_lookbacks": reversal,
        "trend_weights": weights,
    }


def _run_cached_workload(
    prices: pd.Series,
    settings: Mapping[str, Any],
) -> tuple[walk_forward.WalkForwardResult, int]:
    captured_cache: dict[StrategyConfig, pd.DataFrame] | None = None
    optimized_helper = walk_forward._run_cached_candidate_window

    def capture_cache(
        point_in_time_history: pd.Series,
        complete_history: pd.Series,
        cache: dict[StrategyConfig, pd.DataFrame],
        config: StrategyConfig,
        start: pd.Timestamp,
        end: pd.Timestamp,
        previous_position: float,
    ) -> pd.DataFrame:
        nonlocal captured_cache
        captured_cache = cache
        return optimized_helper(
            point_in_time_history,
            complete_history,
            cache,
            config,
            start,
            end,
            previous_position,
        )

    result = cache_benchmark._run_with_candidate_window(prices, settings, capture_cache)
    if captured_cache is None:
        raise RuntimeError("cached scaling workload did not populate the candidate cache")
    return result, len(captured_cache)


def _write_worker_outputs(
    csv_path: Path,
    config_path: Path,
    axis_size: int,
    result_path: Path,
) -> None:
    prices = load_price_csv(csv_path)
    settings = _scaling_settings(config_path, axis_size)
    pre_workload_peak_rss_bytes = _peak_rss_bytes()
    started = time.perf_counter()
    result, cache_entries = _run_cached_workload(prices, settings)
    elapsed_seconds = time.perf_counter() - started
    peak_rss_bytes = _peak_rss_bytes()
    if peak_rss_bytes < pre_workload_peak_rss_bytes:
        raise AssertionError("process peak RSS decreased during the workload")
    with result_path.open("wb") as handle:
        pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
    result_path.with_suffix(".json").write_text(
        json.dumps(
            {
                "axis_size": axis_size,
                "candidate_count": axis_size**3,
                "elapsed_seconds": elapsed_seconds,
                "pre_workload_peak_rss_bytes": pre_workload_peak_rss_bytes,
                "peak_rss_bytes": peak_rss_bytes,
                "workload_peak_rss_increment_bytes": (peak_rss_bytes - pre_workload_peak_rss_bytes),
                "cache_entries": cache_entries,
            }
        ),
        encoding="utf-8",
    )


def _subprocess_measurement(
    csv_path: Path,
    config_path: Path,
    axis_size: int,
    result_path: Path,
) -> ScalingMeasurement:
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--csv",
            str(csv_path),
            "--config",
            str(config_path),
            "--axis-size",
            str(axis_size),
            "--worker-result-path",
            str(result_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    measurement = json.loads(result_path.with_suffix(".json").read_text(encoding="utf-8"))
    with result_path.open("rb") as handle:
        result = pickle.load(handle)  # noqa: S301 - trusted file from this benchmark's child
    return ScalingMeasurement(
        axis_size=int(measurement["axis_size"]),
        candidate_count=int(measurement["candidate_count"]),
        elapsed_seconds=float(measurement["elapsed_seconds"]),
        peak_rss_bytes=int(measurement["peak_rss_bytes"]),
        workload_peak_rss_increment_bytes=int(measurement["workload_peak_rss_increment_bytes"]),
        cache_entries=int(measurement["cache_entries"]),
        result=result,
    )


def _scaling_medians(
    csv_path: Path,
    config_path: Path,
    axis_sizes: Iterable[int],
    repetitions: int,
) -> list[ScalingMedian]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    sizes = list(axis_sizes)
    if not sizes or len(set(sizes)) != len(sizes):
        raise ValueError("axis_sizes must contain distinct values")
    samples: dict[int, list[ScalingMeasurement]] = {size: [] for size in sizes}
    references: dict[int, walk_forward.WalkForwardResult] = {}
    with tempfile.TemporaryDirectory(prefix="gpt-quant-cache-scaling-") as directory:
        root = Path(directory)
        for repetition in range(repetitions):
            order = sizes if repetition % 2 == 0 else list(reversed(sizes))
            for axis_size in order:
                result_path = root / f"axis-{axis_size}-repetition-{repetition}.pickle"
                measurement = _subprocess_measurement(
                    csv_path,
                    config_path,
                    axis_size,
                    result_path,
                )
                if measurement.axis_size != axis_size:
                    raise AssertionError("worker returned the wrong axis size")
                if measurement.candidate_count != axis_size**3:
                    raise AssertionError("worker returned the wrong candidate count")
                reference = references.get(axis_size)
                if reference is None:
                    references[axis_size] = measurement.result
                else:
                    cache_benchmark._assert_equal(reference, measurement.result)
                samples[axis_size].append(measurement)
    medians: list[ScalingMedian] = []
    for axis_size in sizes:
        level = samples[axis_size]
        medians.append(
            ScalingMedian(
                axis_size=axis_size,
                candidate_count=axis_size**3,
                median_seconds=statistics.median(sample.elapsed_seconds for sample in level),
                median_peak_rss_bytes=int(
                    statistics.median(sample.peak_rss_bytes for sample in level)
                ),
                median_workload_peak_rss_increment_bytes=int(
                    statistics.median(sample.workload_peak_rss_increment_bytes for sample in level)
                ),
                median_cache_entries=int(
                    statistics.median(sample.cache_entries for sample in level)
                ),
            )
        )
    return medians


def _parse_axis_sizes(value: str) -> list[int]:
    sizes = [int(item) for item in value.split(",") if item]
    if not sizes:
        raise ValueError("axis sizes must not be empty")
    for size in sizes:
        if size < 1 or size > 4:
            raise ValueError("axis sizes must be between 1 and 4")
    if len(set(sizes)) != len(sizes):
        raise ValueError("axis sizes must be distinct")
    return sizes


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure cached walk-forward runtime and peak RSS across search-grid sizes."
    )
    parser.add_argument("--csv", required=True)
    parser.add_argument("--config", default="config/okx_research.json")
    parser.add_argument("--axis-sizes", default="1,2,3,4")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--axis-size", type=int)
    parser.add_argument("--worker-result-path", type=Path)
    args = parser.parse_args()

    csv_path = Path(args.csv)
    config_path = Path(args.config)
    if args.axis_size is not None:
        if args.worker_result_path is None:
            parser.error("--worker-result-path is required with --axis-size")
        _write_worker_outputs(csv_path, config_path, args.axis_size, args.worker_result_path)
        return
    if args.worker_result_path is not None:
        parser.error("--worker-result-path is only valid with --axis-size")

    axis_sizes = _parse_axis_sizes(args.axis_sizes)
    medians = _scaling_medians(
        csv_path,
        config_path,
        axis_sizes,
        args.repetitions,
    )
    prices = load_price_csv(csv_path)
    print(f"csv_sha256={cache_benchmark._sha256(csv_path)}")
    print(f"observations={len(prices)}")
    print("repeated_result_equivalence=exact")
    for measurement in medians:
        prefix = f"candidates_{measurement.candidate_count}"
        print(f"{prefix}_median_seconds={measurement.median_seconds:.9f}")
        print(f"{prefix}_median_peak_rss_bytes={measurement.median_peak_rss_bytes}")
        print(
            f"{prefix}_median_workload_peak_rss_increment_bytes="
            f"{measurement.median_workload_peak_rss_increment_bytes}"
        )
        print(f"{prefix}_median_cache_entries={measurement.median_cache_entries}")
    smallest = medians[0]
    largest = medians[-1]
    print(f"runtime_growth_ratio={largest.median_seconds / smallest.median_seconds:.3f}x")
    print(
        "peak_rss_growth_ratio="
        f"{largest.median_peak_rss_bytes / smallest.median_peak_rss_bytes:.3f}x"
    )
    if smallest.median_workload_peak_rss_increment_bytes > 0:
        increment_ratio = (
            largest.median_workload_peak_rss_increment_bytes
            / smallest.median_workload_peak_rss_increment_bytes
        )
        print(f"workload_peak_rss_increment_growth_ratio={increment_ratio:.3f}x")


if __name__ == "__main__":
    main()
