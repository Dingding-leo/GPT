from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_peak_benchmark_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    benchmarks = Path(__file__).parents[1] / "benchmarks"
    monkeypatch.syspath_prepend(str(benchmarks))
    path = benchmarks / "run_walk_forward_cache_peak.py"
    spec = importlib.util.spec_from_file_location("run_walk_forward_cache_peak", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load walk-forward cache peak benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paired_peak_benchmark_alternates_order_and_checks_each_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _load_peak_benchmark_module(monkeypatch)
    baseline_result = object()
    optimized_result = object()
    calls: list[str] = []

    def baseline() -> object:
        calls.append("baseline")
        return baseline_result

    def optimized() -> object:
        calls.append("optimized")
        return optimized_result

    def traced_peak_result(workload: object) -> tuple[int, object]:
        result = workload()
        return (200 if result is baseline_result else 600), result

    def assert_equal(baseline_value: object, optimized_value: object) -> None:
        calls.append("equivalence")
        assert baseline_value is baseline_result
        assert optimized_value is optimized_result

    monkeypatch.setattr(benchmark, "_traced_peak_result", traced_peak_result)
    monkeypatch.setattr(benchmark.cache_benchmark, "_assert_equal", assert_equal)

    baseline_peak, optimized_peak = benchmark._paired_peak_bytes(
        baseline,
        optimized,
        repetitions=3,
    )

    assert calls == [
        "baseline",
        "optimized",
        "equivalence",
        "optimized",
        "baseline",
        "equivalence",
        "baseline",
        "optimized",
        "equivalence",
    ]
    assert baseline_peak == 200
    assert optimized_peak == 600


def test_paired_peak_benchmark_rejects_empty_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _load_peak_benchmark_module(monkeypatch)

    with pytest.raises(ValueError, match="repetitions must be positive"):
        benchmark._paired_peak_bytes(lambda: object(), lambda: object(), repetitions=0)
