#!/usr/bin/env python3
from __future__ import annotations

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
    "BTC-USDT/snapshot/okx-BTC-USDT-1H.csv": (
        "c48322ba3fc80ee6e2b71b71ecf2c5f04d962fbfe87544f9f5cf84e08f49ccc9"
    ),
    "BTC-USDT/snapshot/okx-BTC-USDT-1H.raw.json": (
        "0dd217487e3879ec7ee1cf2e23609259a403c37147c5f302871266f2f404b38b"
    ),
    "BTC-USDT/snapshot/okx-BTC-USDT-1H.metadata.json": (
        "a138d8aff8f413086dfd4a2a67d1c3d078a79dcd346f349e77e19799d674a430"
    ),
    "ETH-USDT/snapshot/okx-ETH-USDT-1H.csv": (
        "6fe601b0806fcf86ffd627de8df3db6350b909dff93000487a5a5b783812016d"
    ),
    "ETH-USDT/snapshot/okx-ETH-USDT-1H.raw.json": (
        "88b410908ee6c06cfc1332d9995e23b1d21e9bea170414896aa805070da34c5a"
    ),
    "ETH-USDT/snapshot/okx-ETH-USDT-1H.metadata.json": (
        "777d8eade157f80c5ea6e56084c2027f02e0bed09ca37f7cedd4968e16fa594f"
    ),
}
_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verify_inputs(root: Path) -> None:
    for relative, expected in _EXPECTED_SHA256.items():
        actual = _sha256(root / relative)
        if actual != expected:
            raise ValueError(f"benchmark input hash mismatch for {relative}: {actual}")


def _inputs(root: Path, instrument: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    snapshot = root / instrument / "snapshot"
    evidence_pages = json.loads((snapshot / f"okx-{instrument}-1H.raw.json").read_text())
    metadata = json.loads((snapshot / f"okx-{instrument}-1H.metadata.json").read_text())
    if not isinstance(evidence_pages, list) or not evidence_pages:
        raise ValueError("benchmark evidence pages must be a non-empty list")
    payloads = [page["payload"] for page in evidence_pages]
    if metadata.get("bar") != "1H" or metadata.get("observations") != 43_828:
        raise ValueError("benchmark metadata is not the canonical five-year OKX 1H snapshot")
    return payloads, metadata


def _fetch(
    payloads: list[dict[str, Any]],
    metadata: dict[str, Any],
    *,
    discard_precomputed_bytes: bool,
):
    page_number = 0

    def getter(url: str, timeout: float) -> dict[str, Any]:
        nonlocal page_number
        page = payloads[page_number]
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
            inst_id=metadata["instrument_id"],
            bar="1H",
            start=metadata["requested_start"],
            end=metadata["requested_end"],
            base_url=metadata["base_url"],
            limit=metadata["limit"],
            max_pages=metadata["max_pages"],
            pause_seconds=0.0,
            timeout=20.0,
            get_json=getter,
        )
    finally:
        okx_module.OKXCandleSnapshot = real_snapshot
    if page_number != len(payloads):
        raise AssertionError("benchmark did not consume every immutable response page")
    return result


def _median_seconds(workload, samples: int) -> float:
    elapsed: list[float] = []
    for _ in range(samples):
        gc.collect()
        started = time.perf_counter()
        workload()
        elapsed.append(time.perf_counter() - started)
    return statistics.median(elapsed)


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
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    if args.samples <= 0:
        raise ValueError("samples must be positive")
    _verify_inputs(args.artifact_dir)

    records: dict[str, Any] = {}
    all_baseline: list[float] = []
    all_optimized: list[float] = []
    baseline_peak = 0
    optimized_peak = 0
    for instrument in _INSTRUMENTS:
        payloads, metadata = _inputs(args.artifact_dir, instrument)
        fixed_fetched_at = datetime.fromisoformat(metadata["fetched_at_utc"])

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return fixed_fetched_at.replace(tzinfo=None)
                return fixed_fetched_at.astimezone(tz)

        okx_module.datetime = FixedDateTime

        def baseline():
            return _fetch(payloads, metadata, discard_precomputed_bytes=True)

        def optimized():
            return _fetch(payloads, metadata, discard_precomputed_bytes=False)

        baseline_snapshot = baseline()
        optimized_snapshot = optimized()
        if not baseline_snapshot.candles.equals(optimized_snapshot.candles):
            raise AssertionError("optimized candles differ from baseline")
        if baseline_snapshot.raw_pages != optimized_snapshot.raw_pages:
            raise AssertionError("optimized raw pages differ from baseline")
        if baseline_snapshot.metadata != optimized_snapshot.metadata:
            raise AssertionError("optimized metadata differs from baseline")
        baseline_seconds = _median_seconds(baseline, args.samples)
        optimized_seconds = _median_seconds(optimized, args.samples)
        all_baseline.append(baseline_seconds)
        all_optimized.append(optimized_seconds)
        baseline_peak = max(baseline_peak, _peak_bytes(baseline))
        optimized_peak = max(optimized_peak, _peak_bytes(optimized))
        records[instrument] = {
            "observations": len(optimized_snapshot.candles),
            "pages": len(optimized_snapshot.raw_pages),
            "baseline_median_seconds": baseline_seconds,
            "optimized_median_seconds": optimized_seconds,
        }

    baseline_median = statistics.median(all_baseline)
    optimized_median = statistics.median(all_optimized)
    print(
        json.dumps(
            {
                "input_sha256": _EXPECTED_SHA256,
                "samples_per_instrument": args.samples,
                "equivalence": "exact_candles_raw_pages_metadata_and_source_hashes",
                "baseline_median_seconds": baseline_median,
                "optimized_median_seconds": optimized_median,
                "runtime_reduction_fraction": 1.0 - optimized_median / baseline_median,
                "speedup": baseline_median / optimized_median,
                "baseline_peak_bytes": baseline_peak,
                "optimized_peak_bytes": optimized_peak,
                "peak_memory_reduction_fraction": 1.0 - optimized_peak / baseline_peak,
                "records": records,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
