from __future__ import annotations

import math
from collections.abc import Callable

import pandas as pd
import pytest

from gpt_quant.benchmarks import (
    buy_and_hold_frame,
    simple_trend_long_cash_frame,
    volatility_targeted_long_frame,
)

_BenchmarkBuilder = Callable[..., pd.DataFrame]


def test_buy_and_hold_charges_entry_cost_at_evaluation_start(
    btc_usdt_prices: pd.Series,
) -> None:
    prices = btc_usdt_prices.iloc[:700]
    start = prices.index[500]
    frame = buy_and_hold_frame(
        prices,
        transaction_cost_bps=10.0,
        start=start,
    )

    assert frame["turnover"].iloc[0] == pytest.approx(1.0)
    assert frame["trading_cost"].iloc[0] == pytest.approx(0.001)
    assert frame["strategy_return"].iloc[0] == pytest.approx(frame["asset_return"].iloc[0] - 0.001)


@pytest.mark.parametrize(
    "builder",
    [buy_and_hold_frame, volatility_targeted_long_frame, simple_trend_long_cash_frame],
    ids=["buy-and-hold", "volatility-targeted", "trend-long-cash"],
)
@pytest.mark.parametrize(
    "transaction_cost_bps",
    [math.nan, math.inf, -math.inf, -1.0],
    ids=["nan", "positive-infinity", "negative-infinity", "negative"],
)
def test_benchmark_builders_reject_invalid_transaction_costs(
    btc_usdt_prices: pd.Series,
    builder: _BenchmarkBuilder,
    transaction_cost_bps: float,
) -> None:
    prices = btc_usdt_prices.iloc[:250]

    with pytest.raises(
        ValueError,
        match="transaction_cost_bps must be finite and non-negative",
    ):
        builder(prices, transaction_cost_bps=transaction_cost_bps)
