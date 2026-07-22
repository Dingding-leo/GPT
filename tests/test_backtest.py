from __future__ import annotations

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest


def _stateful_window_case(
    btc_usdt_prices: pd.Series,
) -> tuple[pd.Series, StrategyConfig, pd.DataFrame, pd.Timestamp, pd.Timestamp]:
    prices = btc_usdt_prices.iloc[:900]
    config = StrategyConfig(
        momentum_lookback=21,
        reversal_lookback=3,
        target_volatility=0.50,
        trend_weight=0.80,
        reversal_weight=0.20,
        transaction_cost_bps=10.0,
    )
    full = run_backtest(prices, config).frame

    candidates = full.iloc[200:-120]
    cash_entry_turnover = candidates["position"].abs()
    stateful = candidates[
        candidates["position"].abs().gt(0.05)
        & candidates["turnover"].sub(cash_entry_turnover).abs().gt(1e-6)
    ]
    assert not stateful.empty

    start = stateful.index[0]
    end = full.index[full.index.get_loc(start) + 90]
    return prices, config, full, start, end


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


def test_future_observation_cannot_change_prior_positions(btc_usdt_prices: pd.Series) -> None:
    earlier = btc_usdt_prices.iloc[:800]
    extended = btc_usdt_prices.iloc[:801]
    config = StrategyConfig()

    original = run_backtest(earlier, config).frame
    changed = run_backtest(extended, config).frame.loc[original.index]

    pd.testing.assert_series_equal(original["position"], changed["position"])
    pd.testing.assert_series_equal(original["strategy_return"], changed["strategy_return"])


def test_transaction_costs_reduce_growth_for_identical_positions(
    btc_usdt_prices: pd.Series,
) -> None:
    prices = btc_usdt_prices.iloc[:900]
    free = run_backtest(prices, StrategyConfig(transaction_cost_bps=0.0)).frame
    costly = run_backtest(prices, StrategyConfig(transaction_cost_bps=20.0)).frame

    pd.testing.assert_series_equal(free["position"], costly["position"])
    assert costly["nav"].iloc[-1] < free["nav"].iloc[-1]
    assert costly["trading_cost"].sum() > 0.0


def test_long_only_configuration_never_creates_a_short_position(
    btc_usdt_prices: pd.Series,
) -> None:
    prices = btc_usdt_prices.iloc[:800]
    frame = run_backtest(prices, StrategyConfig(min_position=0.0)).frame
    assert frame["position"].min() >= 0.0


def test_windowed_backtest_preserves_prior_state_and_rebases_only_nav(
    btc_usdt_prices: pd.Series,
) -> None:
    prices, config, full, start, end = _stateful_window_case(btc_usdt_prices)
    window = run_backtest(prices, config, start=start, end=end).frame

    expected = full.loc[start:end].copy()
    expected["nav"] = (1.0 + expected["strategy_return"]).cumprod()
    pd.testing.assert_frame_equal(window, expected)

    first = window.iloc[0]
    assert abs(float(first["turnover"]) - abs(float(first["position"]))) > 1e-6


def test_windowed_backtest_first_row_cost_uses_prior_position(
    btc_usdt_prices: pd.Series,
) -> None:
    prices, config, full, start, end = _stateful_window_case(btc_usdt_prices)
    window = run_backtest(prices, config, start=start, end=end).frame

    start_location = full.index.get_loc(start)
    prior_position = float(full["position"].iloc[start_location - 1])
    position = float(window.at[start, "position"])
    asset_return = float(window.at[start, "asset_return"])
    expected_turnover = abs(position - prior_position)
    expected_cost = expected_turnover * config.transaction_cost_bps / 10_000.0
    expected_strategy_return = position * asset_return - expected_cost

    assert expected_turnover != pytest.approx(abs(position))
    assert float(window.at[start, "turnover"]) == pytest.approx(expected_turnover)
    assert float(window.at[start, "trading_cost"]) == pytest.approx(expected_cost)
    assert float(window.at[start, "strategy_return"]) == pytest.approx(expected_strategy_return)
    assert float(window.at[start, "nav"]) == pytest.approx(1.0 + expected_strategy_return)
