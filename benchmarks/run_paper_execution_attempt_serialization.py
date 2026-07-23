#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import statistics
import sys
import time
import tracemalloc
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

from gpt_quant import paper_execution_attempt as optimized
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote

_EXPECTED_BASELINE_SHA256 = "a03579f4a1a399cc805bc4637ff90a6d796280704b2701b3a7e796f1d1244903"
_EXPECTED_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_REAL_DAILY_SOURCE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_INSTRUMENT_SOURCE_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_baseline(path: Path) -> ModuleType:
    actual = _sha256(path)
    if actual != _EXPECTED_BASELINE_SHA256:
        raise ValueError(f"baseline source hash mismatch: {actual}")
    name = "gpt_quant._paper_execution_attempt_baseline"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load baseline paper-execution module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_quote(path: Path) -> tuple[str, str, str, str, datetime]:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != _EXPECTED_RESPONSE_SHA256:
        raise ValueError(f"OKX response hash mismatch: {actual}")
    payload = json.loads(raw)
    data = payload["data"]
    if payload.get("code") != "0" or not isinstance(data, list) or len(data) != 1:
        raise ValueError("OKX response does not contain exactly one successful book snapshot")
    book = data[0]
    bid = book["bids"][0]
    ask = book["asks"][0]
    observed = datetime.fromtimestamp(int(book["ts"]) / 1000, tz=UTC)
    return bid[0], bid[1], ask[0], ask[1], observed


def _workload(module: ModuleType, binding, quote, values: dict[str, object], events: int) -> bytes:
    result = b""
    for _ in range(events):
        result = module.record_paper_execution_attempt(binding, quote, **values).to_json_bytes()
    return result


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
    parser.add_argument("--baseline-source", required=True, type=Path)
    parser.add_argument("--okx-response", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--events", type=int, default=5_000)
    args = parser.parse_args()
    if args.samples < 5 or args.events < 1:
        raise ValueError("samples must be at least 5 and events must be positive")

    baseline = _load_baseline(args.baseline_source)
    bid_price, bid_quantity, ask_price, ask_quantity, observed_at = _load_quote(args.okx_response)
    received_at = observed_at + timedelta(milliseconds=50)
    decision_at = received_at + timedelta(milliseconds=50)
    submitted_at = decision_at + timedelta(milliseconds=50)
    outcome_at = submitted_at + timedelta(milliseconds=50)
    signal_close = observed_at.replace(hour=0, minute=0, second=0, microsecond=0)
    signal_open = signal_close - timedelta(days=1)

    intent = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-five-bps",
        strategy_revision="49a4eefa9e6d349237832d75f9c1c96070c6799c",
        source_data_sha256=_REAL_DAILY_SOURCE_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=signal_open,
        signal_bar_close_utc=signal_close,
        decision_not_before_utc=signal_close + timedelta(milliseconds=1),
        expires_at_utc=signal_close + timedelta(days=1),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    quote = ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=observed_at,
        received_at_utc=received_at,
        bid_price=bid_price,
        bid_quantity=bid_quantity,
        ask_price=ask_price,
        ask_quantity=ask_quantity,
        source_response_sha256=_EXPECTED_RESPONSE_SHA256,
        instrument_snapshot_sha256=_REAL_INSTRUMENT_SOURCE_SHA256,
    )
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=decision_at,
        maximum_age_ms=250,
    )
    values: dict[str, object] = {
        "submitted_at_utc": submitted_at,
        "outcome_at_utc": outcome_at,
        "side": "buy",
        "requested_base_quantity": "0.1",
        "outcome": "filled",
        "filled_base_quantity": "0.1",
        "average_fill_price": ask_price,
        "reason_code": "paper-touch-fill",
    }

    expected = _workload(baseline, binding, quote, values, 1)
    actual = _workload(optimized, binding, quote, values, 1)
    if actual != expected:
        raise AssertionError("optimized attempt bytes differ from exact main baseline")

    baseline_samples: list[float] = []
    optimized_samples: list[float] = []
    variants = (("baseline", baseline), ("optimized", optimized))
    for sample in range(args.samples):
        ordered = variants if sample % 2 == 0 else tuple(reversed(variants))
        for name, module in ordered:
            gc.collect()
            started = time.perf_counter()
            result = _workload(module, binding, quote, values, args.events)
            elapsed = time.perf_counter() - started
            if result != expected:
                raise AssertionError(f"{name} attempt bytes changed during benchmark")
            (baseline_samples if name == "baseline" else optimized_samples).append(elapsed)

    baseline_median = statistics.median(baseline_samples)
    optimized_median = statistics.median(optimized_samples)
    baseline_peak = _peak_bytes(lambda: _workload(baseline, binding, quote, values, args.events))
    optimized_peak = _peak_bytes(lambda: _workload(optimized, binding, quote, values, args.events))
    output = {
        "baseline_source_sha256": _EXPECTED_BASELINE_SHA256,
        "okx_response_sha256": _EXPECTED_RESPONSE_SHA256,
        "samples": args.samples,
        "events_per_sample": args.events,
        "equivalence": "exact_canonical_attempt_bytes",
        "baseline_median_seconds": baseline_median,
        "optimized_median_seconds": optimized_median,
        "baseline_microseconds_per_event": baseline_median / args.events * 1_000_000,
        "optimized_microseconds_per_event": optimized_median / args.events * 1_000_000,
        "runtime_reduction_fraction": 1.0 - optimized_median / baseline_median,
        "speedup": baseline_median / optimized_median,
        "baseline_peak_bytes": baseline_peak,
        "optimized_peak_bytes": optimized_peak,
        "peak_memory_change_fraction": optimized_peak / baseline_peak - 1.0,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
