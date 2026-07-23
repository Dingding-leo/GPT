#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import statistics
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import pandas as pd

import gpt_quant.walk_forward_verify_gate as verify_gate

_EXPECTED_SHA256 = {
    "BTC-USDT/walk_forward_returns.csv": (
        "04a0a5257d1e20f1eb88c70b8a0b010d21f0dc35ccb657ba39f14189e9f20790"
    ),
    "BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv": (
        "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1"
    ),
    "ETH-USDT/walk_forward_returns.csv": (
        "4b69db4a44644a5f830e1518aca93356c0eeacf502dc00ba990bd992b9bd387f"
    ),
    "ETH-USDT/snapshot/okx-ETH-USDT-1Dutc.csv": (
        "842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f"
    ),
}
_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
TimestampParser = Callable[[pd.Series, str], pd.DatetimeIndex]
Workload = Callable[[], object]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _baseline_timestamp_index(values: pd.Series, label: str) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(
        [
            verify_gate._explicit_utc_timestamp(value, f"{label} row {row}")
            for row, value in enumerate(values)
        ],
        name="timestamp",
    )
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{label}s must be unique and increasing")
    return index


def _load_timestamp_workload(root: Path) -> list[tuple[pd.Series, str]]:
    for relative, expected in _EXPECTED_SHA256.items():
        actual = _sha256(root / relative)
        if actual != expected:
            raise ValueError(f"benchmark input hash mismatch for {relative}: {actual}")

    workload: list[tuple[pd.Series, str]] = []
    for instrument in _INSTRUMENTS:
        returns = pd.read_csv(root / instrument / "walk_forward_returns.csv")["timestamp"]
        snapshot = pd.read_csv(root / instrument / "snapshot" / f"okx-{instrument}-1Dutc.csv")[
            "timestamp"
        ]
        workload.extend(
            [
                (returns, "walk-forward returns timestamp"),
                (snapshot, "normalized OKX snapshot timestamp"),
                (returns, "walk-forward returns timestamp"),
            ]
        )
    return workload


def _run_timestamp_workload(
    parser: TimestampParser,
    workload: list[tuple[pd.Series, str]],
    repetitions: int,
) -> list[pd.DatetimeIndex]:
    result: list[pd.DatetimeIndex] = []
    for _ in range(repetitions):
        result = [parser(values, label) for values, label in workload]
    return result


def _run_verifier_workload(
    root: Path,
    parser: TimestampParser,
    repetitions: int,
) -> list[dict[str, float | int | str]]:
    original = verify_gate._timestamp_index
    verify_gate._timestamp_index = parser
    try:
        result: list[dict[str, float | int | str]] = []
        for _ in range(repetitions):
            result = [verify_gate.verify_walk_forward_report(root / item) for item in _INSTRUMENTS]
        return result
    finally:
        verify_gate._timestamp_index = original


def _paired_elapsed(
    baseline: Workload,
    optimized: Workload,
    samples: int,
) -> tuple[float, float]:
    baseline_samples: list[float] = []
    optimized_samples: list[float] = []
    workloads = (("baseline", baseline), ("optimized", optimized))
    for sample in range(samples):
        ordered = workloads if sample % 2 == 0 else tuple(reversed(workloads))
        elapsed: dict[str, float] = {}
        for name, workload in ordered:
            gc.collect()
            started = time.perf_counter()
            workload()
            elapsed[name] = time.perf_counter() - started
        baseline_samples.append(elapsed["baseline"])
        optimized_samples.append(elapsed["optimized"])
    return statistics.median(baseline_samples), statistics.median(optimized_samples)


def _peak_bytes(workload: Workload) -> int:
    gc.collect()
    tracemalloc.start()
    tracemalloc.reset_peak()
    try:
        workload()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak


def _result(
    baseline_seconds: float,
    optimized_seconds: float,
    baseline_peak: int,
    optimized_peak: int,
) -> dict[str, float | int]:
    return {
        "baseline_median_seconds": baseline_seconds,
        "optimized_median_seconds": optimized_seconds,
        "runtime_reduction_fraction": 1.0 - optimized_seconds / baseline_seconds,
        "speedup": baseline_seconds / optimized_seconds,
        "baseline_peak_bytes": baseline_peak,
        "optimized_peak_bytes": optimized_peak,
        "peak_memory_reduction_fraction": 1.0 - optimized_peak / baseline_peak,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--component-samples", type=int, default=21)
    parser.add_argument("--component-repetitions", type=int, default=5)
    parser.add_argument("--verifier-samples", type=int, default=9)
    parser.add_argument("--verifier-repetitions", type=int, default=1)
    args = parser.parse_args()
    counts = (
        args.component_samples,
        args.component_repetitions,
        args.verifier_samples,
        args.verifier_repetitions,
    )
    if any(value <= 0 for value in counts):
        raise ValueError("sample and repetition counts must be positive")

    root = args.artifact_dir
    timestamp_workload = _load_timestamp_workload(root)

    def baseline_timestamp() -> list[pd.DatetimeIndex]:
        return _run_timestamp_workload(
            _baseline_timestamp_index,
            timestamp_workload,
            args.component_repetitions,
        )

    def optimized_timestamp() -> list[pd.DatetimeIndex]:
        return _run_timestamp_workload(
            verify_gate._timestamp_index,
            timestamp_workload,
            args.component_repetitions,
        )

    baseline_indexes = _run_timestamp_workload(_baseline_timestamp_index, timestamp_workload, 1)
    optimized_indexes = _run_timestamp_workload(verify_gate._timestamp_index, timestamp_workload, 1)
    if len(baseline_indexes) != len(optimized_indexes) or not all(
        baseline.equals(optimized)
        for baseline, optimized in zip(baseline_indexes, optimized_indexes, strict=True)
    ):
        raise AssertionError("optimized timestamp indexes differ from the scalar baseline")

    def baseline_verifier() -> list[dict[str, float | int | str]]:
        return _run_verifier_workload(
            root,
            _baseline_timestamp_index,
            args.verifier_repetitions,
        )

    def optimized_verifier() -> list[dict[str, float | int | str]]:
        return _run_verifier_workload(
            root,
            verify_gate._timestamp_index,
            args.verifier_repetitions,
        )

    if _run_verifier_workload(root, _baseline_timestamp_index, 1) != _run_verifier_workload(
        root, verify_gate._timestamp_index, 1
    ):
        raise AssertionError("optimized verifier results differ from the scalar baseline")

    component_baseline, component_optimized = _paired_elapsed(
        baseline_timestamp,
        optimized_timestamp,
        args.component_samples,
    )
    verifier_baseline, verifier_optimized = _paired_elapsed(
        baseline_verifier,
        optimized_verifier,
        args.verifier_samples,
    )
    output = {
        "input_sha256": _EXPECTED_SHA256,
        "timestamp_component": {
            "samples": args.component_samples,
            "repetitions_per_sample": args.component_repetitions,
            "index_builds_per_repetition": len(timestamp_workload),
            "equivalence": "exact_datetime_index",
            **_result(
                component_baseline,
                component_optimized,
                _peak_bytes(
                    lambda: _run_timestamp_workload(
                        _baseline_timestamp_index, timestamp_workload, 1
                    )
                ),
                _peak_bytes(
                    lambda: _run_timestamp_workload(
                        verify_gate._timestamp_index, timestamp_workload, 1
                    )
                ),
            ),
        },
        "full_two_market_verifier": {
            "samples": args.verifier_samples,
            "repetitions_per_sample": args.verifier_repetitions,
            "markets": list(_INSTRUMENTS),
            "equivalence": "exact_verification_dictionary",
            **_result(
                verifier_baseline,
                verifier_optimized,
                _peak_bytes(lambda: _run_verifier_workload(root, _baseline_timestamp_index, 1)),
                _peak_bytes(lambda: _run_verifier_workload(root, verify_gate._timestamp_index, 1)),
            ),
        },
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
