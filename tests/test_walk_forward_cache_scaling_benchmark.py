from __future__ import annotations

import importlib.util
import json
import pickle
from pathlib import Path
from types import ModuleType

import pytest


def _load_scaling_benchmark_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    benchmarks = Path(__file__).parents[1] / "benchmarks"
    monkeypatch.syspath_prepend(str(benchmarks))
    path = benchmarks / "run_walk_forward_cache_scaling.py"
    spec = importlib.util.spec_from_file_location("run_walk_forward_cache_scaling", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load walk-forward cache scaling benchmark")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings() -> dict[str, object]:
    return {
        "momentum_lookbacks": [30, 90, 180],
        "reversal_lookbacks": [2, 5, 10],
        "trend_weights": [0.55, 0.7, 0.85],
    }


def test_scaling_axes_preserve_default_grid_and_extend_to_64(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _load_scaling_benchmark_module(monkeypatch)

    assert benchmark._axis_values(_settings(), 3) == (
        [30, 90, 180],
        [2, 5, 10],
        [0.55, 0.7, 0.85],
    )
    momentum, reversal, weights = benchmark._axis_values(_settings(), 4)
    assert momentum == [30, 90, 180, 240]
    assert reversal == [2, 5, 10, 15]
    assert weights == [0.55, 0.7, 0.85, 0.95]
    assert len(momentum) * len(reversal) * len(weights) == 64


@pytest.mark.parametrize("axis_size", [0, 5])
def test_scaling_axes_reject_unsupported_sizes(
    monkeypatch: pytest.MonkeyPatch,
    axis_size: int,
) -> None:
    benchmark = _load_scaling_benchmark_module(monkeypatch)

    with pytest.raises(ValueError, match="axis_size must be between 1 and 4"):
        benchmark._axis_values(_settings(), axis_size)


def test_linear_fit_reports_persisted_scaling_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _load_scaling_benchmark_module(monkeypatch)
    candidates = [1, 8, 27, 64]

    runtime_fit = benchmark._linear_fit(
        candidates,
        [0.273157908, 0.769003060, 2.016769424, 4.450399261],
    )
    assert runtime_fit.intercept == pytest.approx(0.224923750, abs=1e-9)
    assert runtime_fit.slope == pytest.approx(0.066096347, abs=1e-9)
    assert runtime_fit.r_squared == pytest.approx(0.999939868, abs=1e-9)

    peak_rss_fit = benchmark._linear_fit(
        candidates,
        [87_728_128, 90_005_504, 96_894_976, 110_211_072],
    )
    assert peak_rss_fit.intercept == pytest.approx(
        87_251_205.356,
        abs=1e-3,
    )
    assert peak_rss_fit.slope == pytest.approx(358_348.586, abs=1e-3)
    assert peak_rss_fit.r_squared == pytest.approx(0.999907577, abs=1e-9)


def test_linear_fit_rejects_insufficient_or_degenerate_inputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    benchmark = _load_scaling_benchmark_module(monkeypatch)

    with pytest.raises(ValueError, match="equally sized inputs"):
        benchmark._linear_fit([1.0], [2.0])
    with pytest.raises(ValueError, match="equally sized inputs"):
        benchmark._linear_fit([1.0, 2.0], [3.0])
    with pytest.raises(ValueError, match="distinct x values"):
        benchmark._linear_fit([1.0, 1.0], [2.0, 3.0])


def test_scaling_measurement_alternates_order_and_checks_repetitions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    benchmark = _load_scaling_benchmark_module(monkeypatch)
    calls: list[int | str] = []
    results = {1: object(), 2: object()}

    def subprocess_measurement(
        csv_path: Path,
        config_path: Path,
        axis_size: int,
        result_path: Path,
    ) -> object:
        del csv_path, config_path, result_path
        calls.append(axis_size)
        return benchmark.ScalingMeasurement(
            axis_size=axis_size,
            candidate_count=axis_size**3,
            elapsed_seconds=float(axis_size),
            peak_rss_bytes=axis_size * 100,
            workload_peak_rss_increment_bytes=axis_size * 20,
            cache_entries=axis_size * 5,
            result=results[axis_size],
        )

    def assert_equal(reference: object, repeated: object) -> None:
        calls.append("equivalence")
        assert reference is repeated

    monkeypatch.setattr(
        benchmark,
        "_subprocess_measurement",
        subprocess_measurement,
    )
    monkeypatch.setattr(benchmark.cache_benchmark, "_assert_equal", assert_equal)

    medians = benchmark._scaling_medians(
        tmp_path / "prices.csv",
        tmp_path / "config.json",
        axis_sizes=[1, 2],
        repetitions=3,
    )

    assert calls == [
        1,
        2,
        2,
        "equivalence",
        1,
        "equivalence",
        1,
        "equivalence",
        2,
        "equivalence",
    ]
    assert medians == [
        benchmark.ScalingMedian(1, 1, 1.0, 100, 20, 5),
        benchmark.ScalingMedian(2, 8, 2.0, 200, 40, 10),
    ]


def test_worker_measures_before_result_serialization(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    benchmark = _load_scaling_benchmark_module(monkeypatch)
    result = {"result": "exact"}
    peaks = iter((100, 175))
    times = iter((10.0, 12.5))
    result_path = tmp_path / "result.pickle"

    monkeypatch.setattr(benchmark, "load_price_csv", lambda path: object())
    monkeypatch.setattr(benchmark, "_scaling_settings", lambda path, size: {"axis": size})
    monkeypatch.setattr(benchmark, "_run_cached_workload", lambda prices, settings: (result, 9))
    monkeypatch.setattr(benchmark, "_peak_rss_bytes", lambda: next(peaks))
    monkeypatch.setattr(benchmark.time, "perf_counter", lambda: next(times))

    benchmark._write_worker_outputs(
        tmp_path / "prices.csv",
        tmp_path / "config.json",
        axis_size=2,
        result_path=result_path,
    )

    measurement = json.loads(result_path.with_suffix(".json").read_text())
    assert measurement == {
        "axis_size": 2,
        "candidate_count": 8,
        "elapsed_seconds": 2.5,
        "pre_workload_peak_rss_bytes": 100,
        "peak_rss_bytes": 175,
        "workload_peak_rss_increment_bytes": 75,
        "cache_entries": 9,
    }
    with result_path.open("rb") as handle:
        assert pickle.load(handle) == result


def test_scaling_measurement_rejects_invalid_inputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    benchmark = _load_scaling_benchmark_module(monkeypatch)

    with pytest.raises(ValueError, match="repetitions must be positive"):
        benchmark._scaling_medians(
            tmp_path / "prices.csv",
            tmp_path / "config.json",
            axis_sizes=[1],
            repetitions=0,
        )
    with pytest.raises(ValueError, match="distinct values"):
        benchmark._scaling_medians(
            tmp_path / "prices.csv",
            tmp_path / "config.json",
            axis_sizes=[1, 1],
            repetitions=1,
        )
