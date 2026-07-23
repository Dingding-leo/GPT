from __future__ import annotations

import pandas as pd

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig


def _scalar_rebase_reference(
    frame: pd.DataFrame,
    config: StrategyConfig,
    previous_position: float,
) -> pd.DataFrame:
    reference = frame.copy()
    if reference.empty:
        raise ValueError("requested backtest window is empty")
    first = reference.index[0]
    turnover = abs(float(reference.at[first, "position"]) - previous_position)
    reference.at[first, "turnover"] = turnover
    reference.at[first, "trading_cost"] = turnover * config.transaction_cost_bps / 10_000.0
    reference.at[first, "strategy_return"] = float(reference.at[first, "position"]) * float(
        reference.at[first, "asset_return"]
    ) - float(reference.at[first, "trading_cost"])
    reference["nav"] = (1.0 + reference["strategy_return"]).cumprod()
    return reference


def test_vectorized_rebase_matches_scalar_reference_and_preserves_input(
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
    history = btc_usdt_prices.iloc[:500]
    start = history.index[300]
    end = history.index[399]
    source = walk_forward.run_backtest(history, config, start=start, end=end).frame
    original = source.copy(deep=True)

    expected = _scalar_rebase_reference(source, config, previous_position=0.37)
    actual = walk_forward._rebase_test_window(source, config, previous_position=0.37)

    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    pd.testing.assert_frame_equal(source, original, check_exact=True)
