#!/usr/bin/env python3
from __future__ import annotations

"""Benchmark canonical-byte reuse on an immutable public OKX snapshot."""

import argparse
import gc
import hashlib
import json
import statistics
import time
import tracemalloc
from datetime import datetime
from pathlib import Path
from typing import Any

import gpt_quant.okx as okx_module

_EXPECTED_SHA256 = {
    "BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.csv": (
        "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1"
    ),
    "BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.raw.json": (
        "f211e4dc1a325ec05b33962c45d7bf8fd965f4a86fececce6a25c01540a798c0"
    ),
    "BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.metadata.json": (
        "a452cd15b57d91cbd9d96ea06811dcef7f1ea3340a309f77616cda907172277e"
    ),
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_input_hashes(root: Path) -> None:
    for relative, expected in _EXPECTED_SHA256.items():
        actual = _sha256(root / relative)
        if actual != expected:
            raise ValueError(f"benchmark input hash mismatch for {relative}: {actual}")


def _snapshot_inputs(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = root / "BTC-USDT" / "snapshot"
    raw_pages = json.loads((snapshot / "okx-BTC-USDT-1Dutc.raw.json").read_text())
    metadata = json.loads((snapshot / "okx-BTC-USDT-1Dutc.metadata.json").read_text())
    if not isinstance(raw_pages, list) or not raw_pages:
        raise ValueError("benchmark raw pages must be a non-empty list")
    return raw_pages, metadata


def _fetch(
    raw_pages: list[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    discard_precomputed_bytes: bool,
):
    page_number = 0

    def getter(url: str, timeout: float) -> dict[str, Any]:
        nonlocal page_number
        page = raw_pages[page_number]
        page_number += 1
        return page

    real_snapshot = okx_module.OKXCandleSnapshot
    if discard_precomputed_bytes:

        def baseline_snapshot(**kwargs):
            return real_snapshot(
                candles=kwargs["candles"],
                raw_pages=kwargs["raw_pages"],
                metadata=kwargs["metadata"],
            )

        okx_module.OKXCandleSnapshot = baseline_snapshot
    try:
        result = okx_module.fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            start=metadata["requested_start"],
            limit=metadata["limit"],
            max_pages=metadata["max_pages"],
            pause_seconds=0.0,
            as_of=metadata["freshness_checked_at_utc"],
            get_json=getter,
        )
    finally:
        okx_module.OKXCandleSnapshot = real_snapshot
    if page_number != len(raw_pages):
        raise AssertionError("benchmark did not consume every immutable raw page")
    return result


def _paired_elapsed(baseline, optimized, samples: int) -> tuple[float, float]:
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


def _peak_bytes(workload) -> int:
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

    _verify_input_hashes(args.artifact_dir)
    raw_pages, metadata = _snapshot_inputs(args.artifact_dir)
    fixed_fetched_at = datetime.fromisoformat(metadata["fetched_at_utc"])

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = fixed_fetched_at
            if tz is not None:
                return value.astimezone(tz)
            return value.replace(tzinfo=None)

    okx_module.datetime = FixedDateTime

    def baseline():
        return _fetch(raw_pages, metadata, discard_precomputed_bytes=True)

    def optimized():
        return _fetch(raw_pages, metadata, discard_precomputed_bytes=False)

    baseline_snapshot = baseline()
    optimized_snapshot = optimized()
    if not baseline_snapshot.candles.equals(optimized_snapshot.candles):
        raise AssertionError("optimized candles differ from the baseline")
    if baseline_snapshot.raw_pages != optimized_snapshot.raw_pages:
        raise AssertionError("optimized raw pages differ from the baseline")
    if baseline_snapshot.metadata != optimized_snapshot.metadata:
        raise AssertionError("optimized metadata differs from the baseline")
    if (
        baseline_snapshot._source_normalized_csv_sha256,
        baseline_snapshot._source_raw_pages_sha256,
        baseline_snapshot._source_metadata_sha256,
    ) != (
        optimized_snapshot._source_normalized_csv_sha256,
        optimized_snapshot._source_raw_pages_sha256,
        optimized_snapshot._source_metadata_sha256,
    ):
        raise AssertionError("optimized source hashes differ from the baseline")

    baseline_seconds, optimized_seconds = _paired_elapsed(baseline, optimized, args.samples)
    baseline_peak = _peak_bytes(baseline)
    optimized_peak = _peak_bytes(optimized)
    output = {
        "input_sha256": _EXPECTED_SHA256,
        "samples": args.samples,
        "pages": len(raw_pages),
        "observations": len(optimized_snapshot.candles),
        "equivalence": "exact_candles_raw_pages_metadata_and_source_hashes",
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
