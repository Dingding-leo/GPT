from __future__ import annotations

import pandas as pd

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig


def test_candidate_cache_omits_rebuilt_nav_without_changing_window(
    btc_usdt_prices: pd.Series,
) -> None:
    config = StrategyConfig(
        momentum_lookback=63,
        reversal_lookback=3,
        volatility_lookback=20,
        min_position=0.0,
        transaction_cost_bps=5.0,
        annualization=252,
    )
    complete_history = btc_usdt_prices.iloc[:700]
    end = complete_history.index[499]
    point_in_time_history = complete_history.loc[:end]
    start = point_in_time_history.index[300]
    expected = walk_forward._run_test_window(
        point_in_time_history,
        config,
        start,
        end,
        previous_position=0.0,
    )

    cache: dict[StrategyConfig, pd.DataFrame] = {}
    actual = walk_forward._run_cached_candidate_window(
        point_in_time_history,
        complete_history,
        cache,
        config,
        start,
        end,
        0.0,
    )

    assert len(cache) == 1
    assert "nav" not in cache[config].columns
    assert "nav" in actual.columns
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
