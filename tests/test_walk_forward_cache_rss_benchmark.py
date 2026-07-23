from __future__ import annotations

import importlib.util
import json
import pickle
from pathlib import Path
from types import ModuleType

import pytest


def _load_rss_benchmark_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    benchmarks = Path(__file__).parents[1] / "benchmarks"
    monkeypatch.syspath_prepend(str(benchmarks))
    path = benchmarks / "run_walk_forward_cache_rss.py"
    spec = importlib.util.spec_from_file_location("run_walk_forward_cache_rss", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load walk-forward cache RSS benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_paired_rss_benchmark_alternates_order_and_checks_each_pair(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    benchmark = _load_rss_benchmark_module(monkeypatch)
    baseline_result = object()
    optimized_result = object()
    calls: list[str] = []

    def subprocess_peak_result(
        mode: str,
        csv_path: Path,
        config_path: Path,
        result_path: Path,
    ) -> tuple[int, int, object]:
        del csv_path, config_path, result_path
        calls.append(mode)
        if mode == "baseline":
            return 200, 40, baseline_result
        return 600, 300, optimized_result

    def assert_equal(baseline_value: object, optimized_value: object) -> None:
        calls.append("equivalence")
        assert baseline_value is baseline_result
        assert optimized_value is optimized_result

    monkeypatch.setattr(benchmark, "_subprocess_peak_result", subprocess_peak_result)
    monkeypatch.setattr(benchmark.cache_benchmark, "_assert_equal", assert_equal)

    (
        baseline_peak,
        optimized_peak,
        baseline_increment,
        optimized_increment,
    ) = benchmark._paired_peak_rss_bytes(
        tmp_path / "prices.csv",
        tmp_path / "config.json",
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
    assert baseline_increment == 40
    assert optimized_increment == 300


def test_worker_records_workload_peak_increment_before_serialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    benchmark = _load_rss_benchmark_module(monkeypatch)
    result = {"result": "exact"}
    peaks = iter((100, 175))
    result_path = tmp_path / "result.pickle"

    monkeypatch.setattr(
        benchmark,
        "_load_worker_inputs",
        lambda csv_path, config_path: (object(), {"config": "exact"}),
    )
    monkeypatch.setattr(
        benchmark,
        "_worker_result",
        lambda mode, prices, settings: result,
    )
    monkeypatch.setattr(benchmark, "_peak_rss_bytes", lambda: next(peaks))

    benchmark._write_worker_outputs(
        "optimized",
        tmp_path / "prices.csv",
        tmp_path / "config.json",
        result_path,
    )

    measurement = json.loads(result_path.with_suffix(".json").read_text())
    assert measurement == {
        "pre_workload_peak_rss_bytes": 100,
        "peak_rss_bytes": 175,
        "workload_peak_rss_increment_bytes": 75,
    }
    with result_path.open("rb") as handle:
        assert pickle.load(handle) == result


def test_paired_rss_benchmark_rejects_empty_measurement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    benchmark = _load_rss_benchmark_module(monkeypatch)

    with pytest.raises(ValueError, match="repetitions must be positive"):
        benchmark._paired_peak_rss_bytes(
            tmp_path / "prices.csv",
            tmp_path / "config.json",
            repetitions=0,
        )


def test_peak_rss_normalization_uses_platform_units(monkeypatch: pytest.MonkeyPatch) -> None:
    benchmark = _load_rss_benchmark_module(monkeypatch)

    assert benchmark._normalize_peak_rss_bytes(123, "linux") == 123 * 1024
    assert benchmark._normalize_peak_rss_bytes(123, "darwin") == 123
    with pytest.raises(ValueError, match="peak RSS must be non-negative"):
        benchmark._normalize_peak_rss_bytes(-1, "linux")
