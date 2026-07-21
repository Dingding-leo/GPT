from __future__ import annotations

import pandas as pd

from gpt_quant import StrategyConfig, run_backtest


def test_default_position_floor_tracks_absolute_limit() -> None:
    smaller = StrategyConfig(max_abs_position=0.5)
    larger = StrategyConfig(max_abs_position=2.0)

    assert smaller.min_position == -0.5
    assert larger.min_position == -2.0


def test_position_floor_override_remains_explicit() -> None:
    long_only = StrategyConfig(max_abs_position=0.5, min_position=0.0)
    resized_symmetric = StrategyConfig().with_overrides(max_abs_position=0.5)
    fixed_short_floor = StrategyConfig(min_position=-1.0).with_overrides(max_abs_position=2.0)

    assert long_only.min_position == 0.0
    assert resized_symmetric.min_position == -0.5
    assert fixed_short_floor.min_position == -1.0


def test_implicit_position_floor_survives_non_position_override() -> None:
    cloned = StrategyConfig().with_overrides(momentum_lookback=21)
    resized = cloned.with_overrides(max_abs_position=0.5)

    assert resized.min_position == -0.5


def test_internal_position_floor_state_is_not_serialized() -> None:
    values = StrategyConfig().to_dict()

    assert values["min_position"] == -1.0
    assert "_min_position_implicit" not in values


def test_future_observation_cannot_change_prior_positions(
    btc_usdt_prices: pd.Series,
) -> None:
    earlier = btc_usdt_prices.iloc[:-1]
    extended = btc_usdt_prices
    config = StrategyConfig()

    original = run_backtest(earlier, config).frame
    changed = run_backtest(extended, config).frame.loc[original.index]

    pd.testing.assert_series_equal(original["position"], changed["position"])
    pd.testing.assert_series_equal(original["strategy_return"], changed["strategy_return"])


def test_transaction_costs_reduce_growth_for_identical_positions(
    btc_usdt_prices: pd.Series,
) -> None:
    free = run_backtest(btc_usdt_prices, StrategyConfig(transaction_cost_bps=0.0)).frame
    costly = run_backtest(btc_usdt_prices, StrategyConfig(transaction_cost_bps=20.0)).frame

    pd.testing.assert_series_equal(free["position"], costly["position"])
    assert costly["nav"].iloc[-1] < free["nav"].iloc[-1]
    assert costly["trading_cost"].sum() > 0.0


def test_long_only_configuration_never_creates_a_short_position(
    btc_usdt_prices: pd.Series,
) -> None:
    frame = run_backtest(btc_usdt_prices, StrategyConfig(min_position=0.0)).frame
    assert frame["position"].min() >= 0.0
