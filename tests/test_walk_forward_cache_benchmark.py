from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _load_benchmark_module() -> ModuleType:
    path = Path(__file__).parents[1] / "benchmarks" / "run_walk_forward_cache.py"
    spec = importlib.util.spec_from_file_location("run_walk_forward_cache", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load walk-forward cache benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paired_benchmark_reuses_first_measured_pair_for_equivalence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _load_benchmark_module()
    baseline_result = object()
    optimized_result = object()
    calls: list[str] = []

    def baseline() -> object:
        calls.append("baseline")
        return baseline_result

    def optimized() -> object:
        calls.append("optimized")
        return optimized_result

    def timed_result(workload: object) -> tuple[float, object]:
        result = workload()
        return (2.0 if result is baseline_result else 1.0), result

    def assert_equal(baseline_value: object, optimized_value: object) -> None:
        calls.append("equivalence")
        assert baseline_value is baseline_result
        assert optimized_value is optimized_result

    monkeypatch.setattr(benchmark, "_timed_result", timed_result)
    monkeypatch.setattr(benchmark, "_assert_equal", assert_equal)

    baseline_median, optimized_median = benchmark._paired_medians(
        baseline, optimized, repetitions=3
    )

    assert calls == [
        "baseline",
        "optimized",
        "equivalence",
        "optimized",
        "baseline",
        "baseline",
        "optimized",
    ]
    assert baseline_median == 2.0
    assert optimized_median == 1.0


def test_paired_benchmark_rejects_empty_measurement() -> None:
    benchmark = _load_benchmark_module()

    with pytest.raises(ValueError, match="repetitions must be positive"):
        benchmark._paired_medians(lambda: object(), lambda: object(), repetitions=0)
