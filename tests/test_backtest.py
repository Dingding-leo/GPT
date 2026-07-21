from __future__ import annotations

import pandas as pd

from gpt_quant import StrategyConfig, generate_regime_prices, run_backtest


def test_final_price_cannot_change_already_executed_positions() -> None:
    prices = generate_regime_prices(rows=800, seed=11)
    config = StrategyConfig()

    original = run_backtest(prices, config).frame
    changed_prices = prices.copy()
    changed_prices.iloc[-1] *= 1.80
    changed = run_backtest(changed_prices, config).frame

    pd.testing.assert_series_equal(original["position"], changed["position"])
    assert original["strategy_return"].iloc[-1] != changed["strategy_return"].iloc[-1]


def test_transaction_costs_reduce_growth_for_identical_positions() -> None:
    prices = generate_regime_prices(rows=900, seed=13)
    free = run_backtest(prices, StrategyConfig(transaction_cost_bps=0.0)).frame
    costly = run_backtest(prices, StrategyConfig(transaction_cost_bps=20.0)).frame

    pd.testing.assert_series_equal(free["position"], costly["position"])
    assert costly["nav"].iloc[-1] < free["nav"].iloc[-1]
    assert costly["trading_cost"].sum() > 0.0
