from __future__ import annotations

import pandas as pd

from gpt_quant import StrategyConfig, run_backtest


def test_full_source_selected_path_cache_matches_point_in_time_folds(
    btc_usdt_prices: pd.Series,
) -> None:
    """Future immutable rows must not change earlier target or executed-position paths."""

    prices = btc_usdt_prices.iloc[:800]
    config = StrategyConfig(
        momentum_lookback=63,
        reversal_lookback=5,
        volatility_lookback=20,
        target_volatility=0.12,
        max_abs_position=1.0,
        min_position=0.0,
        trend_weight=0.7,
        reversal_weight=0.3,
        transaction_cost_bps=5.0,
        annualization=365,
    )
    cached_path = run_backtest(prices, config).frame.loc[:, ["target_position", "position"]]

    for start_index, end_index in ((400, 489), (500, 589)):
        test_start = prices.index[start_index]
        test_end = prices.index[end_index]
        point_in_time = run_backtest(
            prices.loc[:test_end],
            config,
            start=test_start,
            end=test_end,
        ).frame.loc[:, ["target_position", "position"]]
        cached_fold = cached_path.loc[test_start:test_end]

        pd.testing.assert_frame_equal(cached_fold, point_in_time, check_exact=True)
