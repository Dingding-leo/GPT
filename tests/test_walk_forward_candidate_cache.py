from __future__ import annotations

from collections.abc import Callable

import pandas as pd
import pytest

import gpt_quant.walk_forward as walk_forward
from gpt_quant import BacktestResult, StrategyConfig

CandidateWindow = Callable[
    [
        pd.Series,
        pd.Series,
        dict[StrategyConfig, pd.DataFrame],
        StrategyConfig,
        pd.Timestamp,
        pd.Timestamp,
        float,
    ],
    pd.DataFrame,
]


def _settings() -> dict[str, object]:
    return {
        "base_config": StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=252,
        ),
        "momentum_lookbacks": (21, 63),
        "reversal_lookbacks": (3,),
        "trend_weights": (0.6, 0.8),
        "selection_bars": 300,
        "test_bars": 100,
        "cost_multipliers": (1.0, 2.0, 4.0),
    }


def _legacy_candidate_window(
    point_in_time_history: pd.Series,
    complete_history: pd.Series,
    cache: dict[StrategyConfig, pd.DataFrame],
    config: StrategyConfig,
    start: pd.Timestamp,
    end: pd.Timestamp,
    previous_position: float,
) -> pd.DataFrame:
    del complete_history, cache
    return walk_forward._run_test_window(
        point_in_time_history,
        config,
        start,
        end,
        previous_position,
    )


def _run_with_candidate_window(
    prices: pd.Series,
    helper: CandidateWindow,
) -> walk_forward.WalkForwardResult:
    original = walk_forward._run_cached_candidate_window
    walk_forward._run_cached_candidate_window = helper
    try:
        return walk_forward.run_walk_forward_research(prices, **_settings())
    finally:
        walk_forward._run_cached_candidate_window = original


def _assert_results_equal(
    baseline: walk_forward.WalkForwardResult,
    optimized: walk_forward.WalkForwardResult,
) -> None:
    baseline_payload = baseline.to_dict()
    optimized_payload = optimized.to_dict()
    baseline_payload.pop("generated_at_utc")
    optimized_payload.pop("generated_at_utc")
    assert baseline_payload == optimized_payload
    pd.testing.assert_frame_equal(
        baseline.combined_frame,
        optimized.combined_frame,
        check_exact=True,
    )
    assert baseline.benchmark_frames.keys() == optimized.benchmark_frames.keys()
    for name in baseline.benchmark_frames:
        pd.testing.assert_frame_equal(
            baseline.benchmark_frames[name],
            optimized.benchmark_frames[name],
            check_exact=True,
        )
    assert baseline.perturbation_frames.keys() == optimized.perturbation_frames.keys()
    for name in baseline.perturbation_frames:
        pd.testing.assert_frame_equal(
            baseline.perturbation_frames[name],
            optimized.perturbation_frames[name],
            check_exact=True,
        )


def test_candidate_cache_preserves_complete_walk_forward_result(
    btc_usdt_prices: pd.Series,
) -> None:
    prices = btc_usdt_prices.iloc[:600]

    baseline = _run_with_candidate_window(prices, _legacy_candidate_window)
    optimized = _run_with_candidate_window(prices, walk_forward._run_cached_candidate_window)

    assert len(baseline.folds) == 3
    assert len(optimized.folds) == 3
    _assert_results_equal(baseline, optimized)


def test_candidate_cache_runs_each_configuration_once_and_ignores_later_real_bars(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = StrategyConfig(
        momentum_lookback=63,
        reversal_lookback=3,
        volatility_lookback=20,
        min_position=0.0,
        transaction_cost_bps=5.0,
        annualization=252,
    )
    shorter_history = btc_usdt_prices.iloc[:700]
    longer_history = btc_usdt_prices.iloc[:800]
    start = shorter_history.index[300]
    end = shorter_history.index[499]
    expected = walk_forward._run_test_window(
        shorter_history.loc[:end],
        config,
        start,
        end,
        previous_position=0.0,
    )

    calls = 0
    original = walk_forward.run_backtest

    def counted_run_backtest(*args: object, **kwargs: object) -> BacktestResult:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(walk_forward, "run_backtest", counted_run_backtest)
    cache: dict[StrategyConfig, pd.DataFrame] = {}
    first = walk_forward._run_cached_candidate_window(
        shorter_history.loc[:end],
        longer_history,
        cache,
        config,
        start,
        end,
        0.0,
    )
    second = walk_forward._run_cached_candidate_window(
        longer_history.loc[:end],
        longer_history,
        cache,
        config,
        start,
        end,
        0.0,
    )

    assert calls == 1
    assert len(cache) == 1
    pd.testing.assert_frame_equal(first, expected, check_exact=True)
    pd.testing.assert_frame_equal(second, expected, check_exact=True)


def test_candidate_cache_reuses_perturbation_configurations(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prices = btc_usdt_prices.iloc[:600]
    calls: dict[StrategyConfig, int] = {}
    original = walk_forward.run_backtest

    def counted_run_backtest(*args: object, **kwargs: object) -> BacktestResult:
        config = args[1]
        assert isinstance(config, StrategyConfig)
        calls[config] = calls.get(config, 0) + 1
        return original(*args, **kwargs)

    monkeypatch.setattr(walk_forward, "run_backtest", counted_run_backtest)
    result = walk_forward.run_walk_forward_research(prices, **_settings())

    assert len(result.folds) == 3
    assert calls
    assert set(calls.values()) == {1}
