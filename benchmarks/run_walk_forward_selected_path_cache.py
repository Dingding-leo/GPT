#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import math
import statistics
import time
import tracemalloc
from collections.abc import Callable, Mapping
from pathlib import Path

import numpy as np
import pandas as pd

import gpt_quant.walk_forward_verify_gate as verify_gate
from gpt_quant.backtest import run_backtest
from gpt_quant.config import StrategyConfig

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
PathValidator = Callable[[Mapping[str, object], pd.DataFrame, pd.Series], tuple[int, int]]
Workload = Callable[[], object]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_input_hashes(root: Path) -> None:
    for relative, expected in _EXPECTED_SHA256.items():
        actual = _sha256(root / relative)
        if actual != expected:
            raise ValueError(f"benchmark input hash mismatch for {relative}: {actual}")


def _baseline_selected_position_paths(
    payload: Mapping[str, object],
    persisted: pd.DataFrame,
    source_close: pd.Series,
) -> tuple[int, int]:
    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        raise ValueError("walk-forward report folds must be a non-empty list")

    persisted_index = verify_gate._timestamp_index(
        persisted["timestamp"],
        "walk-forward returns timestamp",
    )
    fold_values = verify_gate._numeric(persisted, "fold")
    if (fold_values <= 0.0).any() or not np.equal(
        fold_values, np.floor(fold_values)
    ).all():
        raise ValueError("walk-forward fold identifiers must be positive integers")

    indexed = persisted.copy()
    indexed.index = persisted_index
    indexed["fold"] = fold_values.to_numpy(dtype=int, copy=False)
    indexed["target_position"] = verify_gate._numeric(
        persisted, "target_position"
    ).to_numpy(copy=False)
    indexed["position"] = verify_gate._numeric(persisted, "position").to_numpy(copy=False)

    expected_fold_ids: list[int] = []
    verified_rows = 0
    for ordinal, fold in enumerate(folds, start=1):
        fold_mapping = verify_gate._mapping(fold, f"fold {ordinal}")
        fold_id_value = fold_mapping.get("fold")
        if isinstance(fold_id_value, bool) or not isinstance(fold_id_value, int):
            raise ValueError(f"fold {ordinal} identifier must be a positive integer")
        fold_id = int(fold_id_value)
        if fold_id <= 0:
            raise ValueError(f"fold {ordinal} identifier must be a positive integer")
        if fold_id in expected_fold_ids:
            raise ValueError(f"walk-forward report contains duplicate fold {fold_id}")
        expected_fold_ids.append(fold_id)

        fold_frame = indexed.loc[indexed["fold"] == fold_id]
        if fold_frame.empty:
            raise ValueError(f"walk-forward returns CSV is missing fold {fold_id}")
        test_start = verify_gate._explicit_utc_timestamp(
            fold_mapping.get("test_start"),
            f"fold {fold_id} test_start",
        )
        test_end = verify_gate._explicit_utc_timestamp(
            fold_mapping.get("test_end"),
            f"fold {fold_id} test_end",
        )
        if fold_frame.index[0] != test_start or fold_frame.index[-1] != test_end:
            raise ValueError(f"fold {fold_id} test boundaries do not match persisted returns")

        selected_parameters = verify_gate._mapping(
            fold_mapping.get("selected_parameters"),
            f"fold {fold_id} selected_parameters",
        )
        selected_config = StrategyConfig(**dict(selected_parameters))
        if not math.isclose(
            selected_config.transaction_cost_bps,
            verify_gate._BASELINE_FEE_BPS,
            rel_tol=0.0,
            abs_tol=verify_gate._ACCOUNTING_TOLERANCE,
        ):
            raise ValueError(f"fold {fold_id} selected fee must match the canonical baseline")

        expected_fold = run_backtest(
            source_close.loc[:test_end],
            selected_config,
            start=test_start,
            end=test_end,
        ).frame
        if not expected_fold.index.equals(fold_frame.index):
            raise ValueError(f"fold {fold_id} source timestamps do not match persisted returns")
        verify_gate._assert_accounting(
            f"fold {fold_id} source target_position",
            fold_frame["target_position"],
            expected_fold["target_position"],
        )
        verify_gate._assert_accounting(
            f"fold {fold_id} source position",
            fold_frame["position"],
            expected_fold["position"],
        )
        verified_rows += len(fold_frame)

    actual_fold_ids = sorted(int(value) for value in indexed["fold"].unique())
    if actual_fold_ids != sorted(expected_fold_ids):
        raise ValueError("walk-forward report fold identifiers do not match persisted returns")
    return len(expected_fold_ids), verified_rows


def _run_verifier(root: Path, validator: PathValidator) -> list[dict[str, object]]:
    original = verify_gate._validate_selected_position_paths
    verify_gate._validate_selected_position_paths = validator
    try:
        return [verify_gate.verify_walk_forward_report(root / item) for item in _INSTRUMENTS]
    finally:
        verify_gate._validate_selected_position_paths = original


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=21)
    args = parser.parse_args()
    if args.samples <= 0:
        raise ValueError("samples must be positive")

    root = args.artifact_dir
    _verify_input_hashes(root)

    baseline = lambda: _run_verifier(root, _baseline_selected_position_paths)
    optimized = lambda: _run_verifier(root, verify_gate._validate_selected_position_paths)
    if baseline() != optimized():
        raise AssertionError("cached verifier output differs from the per-fold baseline")

    baseline_seconds, optimized_seconds = _paired_elapsed(
        baseline,
        optimized,
        args.samples,
    )
    baseline_peak = _peak_bytes(baseline)
    optimized_peak = _peak_bytes(optimized)
    output = {
        "input_sha256": _EXPECTED_SHA256,
        "markets": list(_INSTRUMENTS),
        "samples": args.samples,
        "equivalence": "exact_complete_verification_dictionary",
        "baseline_median_seconds": baseline_seconds,
        "optimized_median_seconds": optimized_seconds,
        "runtime_reduction_fraction": 1.0 - optimized_seconds / baseline_seconds,
        "speedup": baseline_seconds / optimized_seconds,
        "baseline_peak_bytes": baseline_peak,
        "optimized_peak_bytes": optimized_peak,
        "peak_memory_reduction_fraction": 1.0 - optimized_peak / baseline_peak,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
