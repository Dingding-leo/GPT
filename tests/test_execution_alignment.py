from __future__ import annotations

import pandas as pd

from gpt_quant import StrategyConfig, run_backtest


def test_one_bar_execution_accounting_identity(btc_usdt_prices: pd.Series) -> None:
    prices = btc_usdt_prices.iloc[:900]
    config = StrategyConfig(
        transaction_cost_bps=10.0,
        min_position=0.0,
        annualization=365,
    )

    frame = run_backtest(prices, config).frame

    expected_asset_return = prices.pct_change().fillna(0.0).rename("asset_return")
    pd.testing.assert_series_equal(frame["asset_return"], expected_asset_return)

    expected_position = frame["target_position"].shift(1).fillna(0.0).rename("position")
    pd.testing.assert_series_equal(frame["position"], expected_position)

    expected_turnover = (
        expected_position.diff().abs().fillna(expected_position.abs()).rename("turnover")
    )
    pd.testing.assert_series_equal(frame["turnover"], expected_turnover)

    expected_cost = (expected_turnover * config.transaction_cost_bps / 10_000.0).rename(
        "trading_cost"
    )
    pd.testing.assert_series_equal(frame["trading_cost"], expected_cost)

    expected_return = (expected_position * expected_asset_return - expected_cost).rename(
        "strategy_return"
    )
    pd.testing.assert_series_equal(frame["strategy_return"], expected_return)

    expected_nav = (1.0 + expected_return).cumprod().rename("nav")
    pd.testing.assert_series_equal(frame["nav"], expected_nav)

    assert frame["target_position"].ne(frame["position"]).any()
