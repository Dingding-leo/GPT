#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import statistics
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import numpy as np
import pandas as pd

from gpt_quant.config import StrategyConfig
from gpt_quant.walk_forward import run_walk_forward_research

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


def _worker() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config")
    parser.add_argument("--inst-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--manifest-path", required=True)
    parser.add_argument("--bar")
    parser.add_argument("--base-url")
    parser.add_argument("--start")
    parser.add_argument("--end")
    parser.add_argument("--max-pages")
    args = parser.parse_args()

    source_root = Path(os.environ["OKX_BATCH_BENCHMARK_SOURCE_ROOT"])
    instrument_root = source_root / args.inst_id
    snapshot_path = instrument_root / "snapshot" / f"okx-{args.inst_id}-1Dutc.csv"
    snapshot_bytes = snapshot_path.read_bytes()
    expected_sha256 = _EXPECTED_SNAPSHOT_SHA256[args.inst_id]
    if _sha256(snapshot_bytes) != expected_sha256:
        raise ValueError(f"immutable snapshot hash mismatch for {args.inst_id}")

    effective = json.loads((instrument_root / "effective_config.json").read_text(encoding="utf-8"))
    base_config = StrategyConfig(**effective["strategy"])
    if base_config.transaction_cost_bps != 5.0:
        raise ValueError("benchmark requires the canonical 5 bps one-way fee baseline")
    cost_multipliers = effective["robustness"]["cost_multipliers"]
    if cost_multipliers != [1.0, 1.5, 2.0, 3.0]:
        raise ValueError("benchmark requires 5/7.5/10/15 bps cost sensitivities")

    frame = pd.read_csv(snapshot_path, parse_dates=["timestamp"])
    close = pd.Series(
        frame["close"].to_numpy(dtype=float),
        index=pd.DatetimeIndex(frame["timestamp"]),
        name="close",
    )
    result = run_walk_forward_research(
        close,
        base_config=base_config,
        momentum_lookbacks=effective["search"]["momentum_lookbacks"],
        reversal_lookbacks=effective["search"]["reversal_lookbacks"],
        trend_weights=effective["search"]["trend_weights"],
        selection_bars=effective["search"]["selection_bars"],
        test_bars=effective["search"]["test_bars"],
        cost_multipliers=cost_multipliers,
        provenance={
            "provider": "OKX",
            "instrument_id": args.inst_id,
            "snapshot_sha256": expected_sha256,
        },
    )
    payload = {
        "instrument_id": args.inst_id,
        "snapshot_sha256": expected_sha256,
        "exchange_fee_bps_one_way": 5.0,
        "fixed_path_cost_sensitivities_bps": [7.5, 10.0, 15.0],
        "spread": "not_modeled",
        "slippage": "not_modeled",
        "market_impact": "not_modeled",
        "latency": "not_modeled",
        "data_summary": _jsonable(result.data_summary),
        "settings": _jsonable(result.settings),
        "folds": _jsonable(result.folds),
        "aggregate_metrics": _jsonable(result.aggregate_metrics),
        "benchmark_metrics": _jsonable(result.benchmark_metrics),
        "benchmark_assessment": _jsonable(result.benchmark_assessment),
        "cost_stress_metrics": _jsonable(result.cost_stress_metrics),
        "perturbation_metrics": _jsonable(result.perturbation_metrics),
        "parameter_stability": _jsonable(result.parameter_stability),
        "fold_stability": _jsonable(result.fold_stability),
        "robustness_status": result.robustness_status,
        "combined_frame_sha256": _frame_sha256(result.combined_frame),
        "benchmark_frame_sha256": {
            name: _frame_sha256(value) for name, value in sorted(result.benchmark_frames.items())
        },
        "perturbation_frame_sha256": {
            name: _frame_sha256(value) for name, value in sorted(result.perturbation_frames.items())
        },
    }
    output_bytes = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.json").write_bytes(output_bytes)
    run_id = _sha256(output_bytes)
    manifest_path = Path(args.manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "instrument_id": args.inst_id,
                "result_sha256": run_id,
                "run_id": run_id,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


def _load_batch_module() -> Any:
    path = Path(__file__).parents[1] / "scripts" / "run_okx_research_batch.py"
    spec = importlib.util.spec_from_file_location("run_okx_research_batch", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load batch runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_once(batch: Any, root: Path, *, max_workers: int) -> tuple[bytes, Any]:
    output_root = root / "output"
    manifest_root = root / "child-manifests"
    jobs = tuple(
        batch._Job(
            instrument_id=instrument_id,
            command=batch._build_command(
                runner=Path(__file__),
                instrument_id=instrument_id,
                output_dir=output_root / instrument_id,
                manifest_path=manifest_root / f"{instrument_id}.jsonl",
                config="unused-by-benchmark-worker.json",
                bar=None,
                base_url=None,
                start=None,
                end=None,
                max_pages=None,
            ),
        )
        for instrument_id in _INSTRUMENTS
    )
    _, metrics = batch._run_processes(jobs, max_workers=max_workers)
    combined = root / "experiment-manifest.jsonl"
    batch._publish_manifest(
        tuple(
            (instrument_id, manifest_root / f"{instrument_id}.jsonl")
            for instrument_id in _INSTRUMENTS
        ),
        combined,
    )
    evidence = (
        b"".join(
            (output_root / instrument_id / "result.json").read_bytes()
            for instrument_id in _INSTRUMENTS
        )
        + combined.read_bytes()
    )
    return evidence, metrics


def _controller() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=5)
    args = parser.parse_args()
    if args.samples < 3:
        raise ValueError("samples must be at least 3")
    for instrument_id, expected in _EXPECTED_SNAPSHOT_SHA256.items():
        path = args.source_root / instrument_id / "snapshot" / f"okx-{instrument_id}-1Dutc.csv"
        if _sha256(path.read_bytes()) != expected:
            raise ValueError(f"immutable snapshot hash mismatch for {instrument_id}")

    batch = _load_batch_module()
    previous_source = os.environ.get("OKX_BATCH_BENCHMARK_SOURCE_ROOT")
    os.environ["OKX_BATCH_BENCHMARK_SOURCE_ROOT"] = str(args.source_root.resolve())
    baseline_seconds: list[float] = []
    optimized_seconds: list[float] = []
    baseline_peak: list[int] = []
    optimized_peak: list[int] = []
    try:
        for sample in range(args.samples):
            with TemporaryDirectory(prefix="okx-batch-benchmark-") as name:
                root = Path(name)
                order = (1, 2) if sample % 2 == 0 else (2, 1)
                results: dict[int, tuple[bytes, Any]] = {}
                for workers in order:
                    results[workers] = _run_once(
                        batch,
                        root / f"workers-{workers}",
                        max_workers=workers,
                    )
                if results[1][0] != results[2][0]:
                    raise AssertionError("parallel research results differ from sequential results")
                baseline_seconds.append(results[1][1].elapsed_seconds)
                optimized_seconds.append(results[2][1].elapsed_seconds)
                if results[1][1].peak_child_rss_bytes is None:
                    raise RuntimeError("aggregate child RSS measurement is unavailable")
                if results[2][1].peak_child_rss_bytes is None:
                    raise RuntimeError("aggregate child RSS measurement is unavailable")
                baseline_peak.append(results[1][1].peak_child_rss_bytes)
                optimized_peak.append(results[2][1].peak_child_rss_bytes)
    finally:
        if previous_source is None:
            os.environ.pop("OKX_BATCH_BENCHMARK_SOURCE_ROOT", None)
        else:
            os.environ["OKX_BATCH_BENCHMARK_SOURCE_ROOT"] = previous_source

    baseline_median = statistics.median(baseline_seconds)
    optimized_median = statistics.median(optimized_seconds)
    baseline_memory = statistics.median(baseline_peak)
    optimized_memory = statistics.median(optimized_peak)
    print(
        json.dumps(
            {
                "source_snapshot_sha256": _EXPECTED_SNAPSHOT_SHA256,
                "samples": args.samples,
                "equivalence": "exact_metric_path_and_manifest_bytes",
                "baseline_max_workers": 1,
                "optimized_max_workers": 2,
                "baseline_median_seconds": baseline_median,
                "optimized_median_seconds": optimized_median,
                "runtime_reduction_percent": (
                    100 * (baseline_median - optimized_median) / baseline_median
                ),
                "speedup": baseline_median / optimized_median,
                "baseline_peak_child_rss_bytes": baseline_memory,
                "optimized_peak_child_rss_bytes": optimized_memory,
                "peak_memory_change_percent": (
                    100 * (optimized_memory - baseline_memory) / baseline_memory
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    if "--inst-id" in sys.argv:
        raise SystemExit(_worker())
    raise SystemExit(_controller())
