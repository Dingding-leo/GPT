#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import resource
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np
import pandas as pd

_EXPECTED_SNAPSHOT_SHA256 = {
    "BTC-USDT": "bbba1e9b36e17b03ff6aed237a4de949b4a39b1d17eaf1b4979627794acb909c",
    "ETH-USDT": "37f33ce7a55786a10f4c8e0f7ff1c870f331792b6ba1712229008480498ea236",
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
    snapshot_path = instrument_root / "snapshot" / f"okx-{args.instrument}-1H.csv"
    snapshot_bytes = snapshot_path.read_bytes()
    expected_sha256 = _EXPECTED_SNAPSHOT_SHA256[args.instrument]
    if _sha256(snapshot_bytes) != expected_sha256:
        raise ValueError(f"immutable 1h snapshot hash mismatch for {args.instrument}")

    effective = json.loads((instrument_root / "effective_config.json").read_text("utf-8"))
    if effective["data"]["bar"] != "1H":
        raise ValueError("benchmark requires canonical OKX 1H data")
    config = StrategyConfig(**effective["strategy"])
    if config.transaction_cost_bps != 5.0:
        raise ValueError("benchmark requires exactly 5 bps one-way fee")
    if effective["robustness"]["cost_multipliers"] != [1.0]:
        raise ValueError("benchmark requires the exact 5 bps-only cost profile")

    frame = pd.read_csv(snapshot_path, parse_dates=["timestamp"])
    close = pd.Series(
        frame["close"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(frame["timestamp"]),
        name="close",
    )

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

    payload = result.to_dict()
    payload.pop("generated_at_utc")
    payload["combined_frame_sha256"] = _frame_sha256(result.combined_frame)
    payload["benchmark_frame_sha256"] = {
        name: _frame_sha256(value) for name, value in sorted(result.benchmark_frames.items())
    }
    payload["perturbation_frame_sha256"] = {
        name: _frame_sha256(value) for name, value in sorted(result.perturbation_frames.items())
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
                "peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                "result_sha256": _sha256(result_bytes),
            },
            sort_keys=True,
        )
    )
    return 0


def _run_batch(*, site: Path, source_root: Path) -> tuple[float, int, tuple[str, ...]]:
    elapsed_seconds = 0.0
    peak_rss_kib = 0
    hashes: list[str] = []
    for instrument in _INSTRUMENTS:
        completed = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--site",
                str(site),
                "--source-root",
                str(source_root),
                "--instrument",
                instrument,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        record = json.loads(completed.stdout)
        elapsed_seconds += float(record["elapsed_seconds"])
        peak_rss_kib = max(peak_rss_kib, int(record["peak_rss_kib"]))
        hashes.append(str(record["result_sha256"]))
    return elapsed_seconds, peak_rss_kib, tuple(hashes)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark exact 1h full walk-forward candidate-score optimization."
    )
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--baseline-site", type=Path)
    parser.add_argument("--optimized-site", type=Path)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--site", type=Path)
    parser.add_argument("--instrument", choices=_INSTRUMENTS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        if args.site is None or args.instrument is None:
            raise ValueError("worker requires --site and --instrument")
        return _worker(args)
    if args.baseline_site is None or args.optimized_site is None:
        raise ValueError("benchmark requires --baseline-site and --optimized-site")
    if args.samples < 1:
        raise ValueError("samples must be positive")

    samples: dict[str, list[float]] = {"baseline": [], "optimized": []}
    peaks: dict[str, list[int]] = {"baseline": [], "optimized": []}
    expected_hashes: tuple[str, ...] | None = None
    sites = {"baseline": args.baseline_site, "optimized": args.optimized_site}
    for sample_number in range(args.samples):
        order = ("baseline", "optimized")
        if sample_number % 2:
            order = tuple(reversed(order))
        for variant in order:
            elapsed, peak, hashes = _run_batch(
                site=sites[variant],
                source_root=args.source_root,
            )
            if expected_hashes is None:
                expected_hashes = hashes
            elif hashes != expected_hashes:
                raise AssertionError("baseline and optimized 1h evidence bytes differ")
            samples[variant].append(elapsed)
            peaks[variant].append(peak)

    baseline_median = statistics.median(samples["baseline"])
    optimized_median = statistics.median(samples["optimized"])
    baseline_peak = max(peaks["baseline"])
    optimized_peak = max(peaks["optimized"])
    summary = {
        "bar": "1H",
        "baseline_median_seconds": baseline_median,
        "baseline_peak_rss_kib": baseline_peak,
        "cost_profile": "5_bps_one_way_only",
        "equivalence": "exact_metric_fold_path_and_frame_hashes",
        "optimized_median_seconds": optimized_median,
        "optimized_peak_rss_kib": optimized_peak,
        "peak_rss_change_percent": (optimized_peak - baseline_peak) / baseline_peak * 100.0,
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
