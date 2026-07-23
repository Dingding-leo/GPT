#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pickle
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Literal

import run_walk_forward_cache as cache_benchmark

import gpt_quant.walk_forward as walk_forward
from gpt_quant import load_price_csv

WorkerMode = Literal["baseline", "optimized"]
PeakResult = tuple[int, walk_forward.WalkForwardResult]


def _normalize_peak_rss_bytes(raw_peak: int, platform: str) -> int:
    if raw_peak < 0:
        raise ValueError("peak RSS must be non-negative")
    return raw_peak if platform == "darwin" else raw_peak * 1024


def _peak_rss_bytes() -> int:
    try:
        import resource
    except ModuleNotFoundError as exc:  # pragma: no cover - exercised only off Unix
        raise RuntimeError("peak RSS benchmark requires the Unix resource module") from exc
    raw_peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return _normalize_peak_rss_bytes(raw_peak, sys.platform)


def _worker_result(
    mode: WorkerMode,
    csv_path: Path,
    config_path: Path,
) -> walk_forward.WalkForwardResult:
    prices = load_price_csv(csv_path)
    settings = cache_benchmark._settings(config_path)
    helper = (
        cache_benchmark._legacy_candidate_window
        if mode == "baseline"
        else walk_forward._run_cached_candidate_window
    )
    return cache_benchmark._run_with_candidate_window(prices, settings, helper)


def _write_worker_outputs(
    mode: WorkerMode,
    csv_path: Path,
    config_path: Path,
    result_path: Path,
) -> None:
    result = _worker_result(mode, csv_path, config_path)
    peak_rss_bytes = _peak_rss_bytes()
    with result_path.open("wb") as handle:
        pickle.dump(result, handle, protocol=pickle.HIGHEST_PROTOCOL)
    measurement_path = result_path.with_suffix(".json")
    measurement_path.write_text(
        json.dumps({"peak_rss_bytes": peak_rss_bytes}),
        encoding="utf-8",
    )


def _subprocess_peak_result(
    mode: WorkerMode,
    csv_path: Path,
    config_path: Path,
    result_path: Path,
) -> PeakResult:
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--csv",
            str(csv_path),
            "--config",
            str(config_path),
            "--worker",
            mode,
            "--result-path",
            str(result_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    measurement_path = result_path.with_suffix(".json")
    measurement = json.loads(measurement_path.read_text(encoding="utf-8"))
    peak_rss_bytes = int(measurement["peak_rss_bytes"])
    with result_path.open("rb") as handle:
        result = pickle.load(handle)  # noqa: S301 - trusted file from this benchmark's child
    return peak_rss_bytes, result


def _paired_peak_rss_bytes(
    csv_path: Path,
    config_path: Path,
    repetitions: int,
) -> tuple[int, int]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    baseline_samples: list[int] = []
    optimized_samples: list[int] = []
    with tempfile.TemporaryDirectory(prefix="gpt-quant-cache-rss-") as directory:
        root = Path(directory)
        for repetition in range(repetitions):
            baseline_path = root / f"baseline-{repetition}.pickle"
            optimized_path = root / f"optimized-{repetition}.pickle"
            if repetition % 2 == 0:
                baseline_peak, baseline_result = _subprocess_peak_result(
                    "baseline", csv_path, config_path, baseline_path
                )
                optimized_peak, optimized_result = _subprocess_peak_result(
                    "optimized", csv_path, config_path, optimized_path
                )
            else:
                optimized_peak, optimized_result = _subprocess_peak_result(
                    "optimized", csv_path, config_path, optimized_path
                )
                baseline_peak, baseline_result = _subprocess_peak_result(
                    "baseline", csv_path, config_path, baseline_path
                )
            cache_benchmark._assert_equal(baseline_result, optimized_result)
            baseline_samples.append(baseline_peak)
            optimized_samples.append(optimized_peak)
    return (
        int(statistics.median(baseline_samples)),
        int(statistics.median(optimized_samples)),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Measure process peak RSS for uncached and cached walk-forward research."
    )
    parser.add_argument("--csv", required=True)
    parser.add_argument("--config", default="config/okx_research.json")
    parser.add_argument("--repetitions", type=int, default=3)
    parser.add_argument("--worker", choices=("baseline", "optimized"))
    parser.add_argument("--result-path", type=Path)
    args = parser.parse_args()

    csv_path = Path(args.csv)
    config_path = Path(args.config)
    if args.worker is not None:
        if args.result_path is None:
            parser.error("--result-path is required in worker mode")
        _write_worker_outputs(args.worker, csv_path, config_path, args.result_path)
        return
    if args.result_path is not None:
        parser.error("--result-path is only valid in worker mode")

    baseline_peak, optimized_peak = _paired_peak_rss_bytes(
        csv_path,
        config_path,
        args.repetitions,
    )
    prices = load_price_csv(csv_path)
    increase = optimized_peak / baseline_peak - 1.0
    print(f"csv_sha256={cache_benchmark._sha256(csv_path)}")
    print(f"observations={len(prices)}")
    print("equivalence=exact")
    print(f"baseline_peak_rss_bytes={baseline_peak}")
    print(f"optimized_peak_rss_bytes={optimized_peak}")
    print(f"peak_rss_increase_percent={increase * 100.0:.2f}")
    print(f"peak_rss_ratio={optimized_peak / baseline_peak:.3f}x")


if __name__ == "__main__":
    main()
