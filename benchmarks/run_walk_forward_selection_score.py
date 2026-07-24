#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tracemalloc
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

_EXPECTED_SNAPSHOT_SHA256 = {
    "BTC-USDT": "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1",
    "ETH-USDT": "842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f",
}
_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _frame_sha256(frame: pd.DataFrame) -> str:
    payload = frame.to_csv(
        index=True,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.17g",
        lineterminator="\n",
    ).encode("utf-8")
    return _sha256(payload)


def _worker(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(Path(args.site).resolve()))
    from gpt_quant.config import StrategyConfig
    from gpt_quant.walk_forward import run_walk_forward_research

    instrument_root = Path(args.source_root) / args.instrument
    snapshot_path = (
        instrument_root / "snapshot" / f"okx-{args.instrument}-1Dutc.csv"
    )
    snapshot_bytes = snapshot_path.read_bytes()
    expected_sha256 = _EXPECTED_SNAPSHOT_SHA256[args.instrument]
    if _sha256(snapshot_bytes) != expected_sha256:
        raise ValueError(f"immutable snapshot hash mismatch for {args.instrument}")

    effective = json.loads(
        (instrument_root / "effective_config.json").read_text(encoding="utf-8")
    )
    config = StrategyConfig(**effective["strategy"])
    if config.transaction_cost_bps != 5.0:
        raise ValueError("benchmark requires the canonical 5 bps one-way fee baseline")
    if effective["robustness"]["cost_multipliers"] != [1.0, 1.5, 2.0, 3.0]:
        raise ValueError("benchmark requires 5/7.5/10/15 bps cost sensitivities")

    frame = pd.read_csv(snapshot_path, parse_dates=["timestamp"])
    close = pd.Series(
        frame["close"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(frame["timestamp"]),
        name="close",
    )

    if args.trace_memory:
        tracemalloc.start()
    started = perf_counter()
    result = run_walk_forward_research(
        close,
        base_config=config,
        momentum_lookbacks=effective["search"]["momentum_lookbacks"],
        reversal_lookbacks=effective["search"]["reversal_lookbacks"],
        trend_weights=effective["search"]["trend_weights"],
        selection_bars=effective["search"]["selection_bars"],
        test_bars=effective["search"]["test_bars"],
        cost_multipliers=effective["robustness"]["cost_multipliers"],
        provenance={
            "provider": "OKX",
            "instrument_id": args.instrument,
            "snapshot_sha256": expected_sha256,
        },
    )
    elapsed_seconds = perf_counter() - started
    if args.trace_memory:
        _, peak_python_bytes = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    else:
        peak_python_bytes = 0

    payload = result.to_dict()
    payload.pop("generated_at_utc")
    payload["combined_frame_sha256"] = _frame_sha256(result.combined_frame)
    payload["benchmark_frame_sha256"] = {
        name: _frame_sha256(value)
        for name, value in sorted(result.benchmark_frames.items())
    }
    payload["perturbation_frame_sha256"] = {
        name: _frame_sha256(value)
        for name, value in sorted(result.perturbation_frames.items())
    }
    result_bytes = (
        json.dumps(
            _jsonable(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    print(
        json.dumps(
            {
                "elapsed_seconds": elapsed_seconds,
                "instrument": args.instrument,
                "peak_python_bytes": peak_python_bytes,
                "result_sha256": _sha256(result_bytes),
            },
            sort_keys=True,
        )
    )
    return 0


def _run_batch(
    *,
    site: Path,
    source_root: Path,
    trace_memory: bool = False,
) -> tuple[float, int, tuple[str, ...]]:
    elapsed_seconds = 0.0
    peak_python_bytes = 0
    hashes: list[str] = []
    for instrument in _INSTRUMENTS:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--site",
            str(site),
            "--source-root",
            str(source_root),
            "--instrument",
            instrument,
        ]
        if trace_memory:
            command.append("--trace-memory")
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
        record = json.loads(completed.stdout)
        elapsed_seconds += float(record["elapsed_seconds"])
        peak_python_bytes = max(peak_python_bytes, int(record["peak_python_bytes"]))
        hashes.append(str(record["result_sha256"]))
    return elapsed_seconds, peak_python_bytes, tuple(hashes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark exact full walk-forward candidate-score optimization."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--baseline-site", type=Path)
    parser.add_argument(
        "--optimized-site",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src",
    )
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--trace-memory", action="store_true")
    parser.add_argument("--skip-memory", action="store_true")
    parser.add_argument("--site", type=Path)
    parser.add_argument("--instrument", choices=_INSTRUMENTS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        if args.site is None or args.instrument is None:
            raise ValueError("worker requires --site and --instrument")
        return _worker(args)
    if args.baseline_site is None:
        raise ValueError("benchmark requires --baseline-site from the exact pre-change wheel")
    if args.samples < 1:
        raise ValueError("samples must be positive")

    samples: dict[str, list[float]] = {"baseline": [], "optimized": []}
    peaks: dict[str, list[int]] = {"baseline": [], "optimized": []}
    expected_hashes: tuple[str, ...] | None = None
    sites = {
        "baseline": args.baseline_site,
        "optimized": args.optimized_site,
    }
    for sample_number in range(args.samples):
        order = ("baseline", "optimized")
        if sample_number % 2:
            order = tuple(reversed(order))
        for variant in order:
            elapsed, _, hashes = _run_batch(
                site=sites[variant],
                source_root=args.source_root,
            )
            if expected_hashes is None:
                expected_hashes = hashes
            elif hashes != expected_hashes:
                raise AssertionError("baseline and optimized evidence bytes differ")
            samples[variant].append(elapsed)

    if not args.skip_memory:
        for variant in ("baseline", "optimized"):
            _, peak, hashes = _run_batch(
                site=sites[variant],
                source_root=args.source_root,
                trace_memory=True,
            )
            if hashes != expected_hashes:
                raise AssertionError("memory probe evidence bytes differ")
            peaks[variant].append(peak)

    baseline_median = statistics.median(samples["baseline"])
    optimized_median = statistics.median(samples["optimized"])
    baseline_peak = max(peaks["baseline"]) if peaks["baseline"] else None
    optimized_peak = max(peaks["optimized"]) if peaks["optimized"] else None
    summary = {
        "baseline_median_seconds": baseline_median,
        "baseline_peak_python_bytes": baseline_peak,
        "equivalence": "exact_metric_fold_path_and_frame_hashes",
        "optimized_median_seconds": optimized_median,
        "optimized_peak_python_bytes": optimized_peak,
        "peak_python_memory_change_percent": (
            (optimized_peak - baseline_peak) / baseline_peak * 100.0
            if baseline_peak is not None and optimized_peak is not None
            else None
        ),
        "result_sha256_by_instrument": dict(
            zip(_INSTRUMENTS, expected_hashes, strict=True)
        ),
        "runtime_reduction_percent": (
            (baseline_median - optimized_median) / baseline_median * 100.0
        ),
        "samples": args.samples,
        "speedup": baseline_median / optimized_median,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
