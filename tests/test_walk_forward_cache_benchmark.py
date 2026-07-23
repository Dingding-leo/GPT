from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig


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


def test_cache_memory_benchmark_measures_nav_omission(
    btc_usdt_prices: pd.Series,
) -> None:
    benchmark = _load_benchmark_module()
    config = StrategyConfig(
        momentum_lookback=63,
        reversal_lookback=3,
        volatility_lookback=20,
        min_position=0.0,
        transaction_cost_bps=5.0,
        annualization=252,
    )
    complete_history = btc_usdt_prices.iloc[:700]
    point_in_time_history = complete_history.iloc[:500]
    start = point_in_time_history.index[300]
    end = point_in_time_history.index[-1]
    full_frame_cache: dict[StrategyConfig, pd.DataFrame] = {}
    optimized_cache: dict[StrategyConfig, pd.DataFrame] = {}

    full_frame = benchmark._full_frame_cached_candidate_window(
        point_in_time_history,
        complete_history,
        full_frame_cache,
        config,
        start,
        end,
        0.0,
    )
    optimized = walk_forward._run_cached_candidate_window(
        point_in_time_history,
        complete_history,
        optimized_cache,
        config,
        start,
        end,
        0.0,
    )

    pd.testing.assert_frame_equal(full_frame, optimized, check_exact=True)
    full_frame_column_bytes = benchmark._cache_column_bytes(full_frame_cache)
    optimized_column_bytes = benchmark._cache_column_bytes(optimized_cache)
    full_frame_index_bytes = benchmark._cache_unique_index_bytes(full_frame_cache)
    optimized_index_bytes = benchmark._cache_unique_index_bytes(optimized_cache)
    full_frame_retained_bytes = benchmark._cache_retained_array_bytes(full_frame_cache)
    optimized_retained_bytes = benchmark._cache_retained_array_bytes(optimized_cache)

    assert "nav" in full_frame_cache[config].columns
    assert "nav" not in optimized_cache[config].columns
    assert full_frame_column_bytes - optimized_column_bytes == len(complete_history) * 8
    assert full_frame_index_bytes == btc_usdt_prices.index.nbytes
    assert optimized_index_bytes == full_frame_index_bytes
    assert full_frame_retained_bytes == full_frame_column_bytes + full_frame_index_bytes
    assert optimized_retained_bytes == optimized_column_bytes + optimized_index_bytes
    assert full_frame_retained_bytes - optimized_retained_bytes == len(complete_history) * 8
    assert 1.0 - optimized_column_bytes / full_frame_column_bytes == pytest.approx(0.125)
    assert 1.0 - optimized_retained_bytes / full_frame_retained_bytes == pytest.approx(
        (len(complete_history) * 8) / full_frame_retained_bytes
    )


def test_cache_memory_accounting_counts_shared_index_buffer_once(
    btc_usdt_prices: pd.Series,
) -> None:
    benchmark = _load_benchmark_module()
    first = pd.DataFrame({"value": [1.0, 2.0]}, index=btc_usdt_prices.index[:2])
    second = pd.DataFrame({"value": [3.0, 4.0]}, index=btc_usdt_prices.index[:2].copy())
    assert first.index is not second.index
    assert benchmark._root_array(first.index.asi8) is benchmark._root_array(
        second.index.asi8
    )

    cache = {
        StrategyConfig(momentum_lookback=10): first,
        StrategyConfig(momentum_lookback=11): second,
    }

    shared_index_bytes = benchmark._root_array(first.index.asi8).nbytes
    assert benchmark._cache_unique_index_bytes(cache) == shared_index_bytes
    assert benchmark._cache_retained_array_bytes(cache) == (
        benchmark._cache_column_bytes(cache) + shared_index_bytes
    )
