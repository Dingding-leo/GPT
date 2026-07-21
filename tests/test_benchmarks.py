from __future__ import annotations

import pandas as pd
import pytest

from gpt_quant.benchmarks import buy_and_hold_frame


def test_buy_and_hold_charges_entry_cost_at_evaluation_start(
    btc_usdt_prices: pd.Series,
) -> None:
    start = btc_usdt_prices.index[400]
    frame = buy_and_hold_frame(
        btc_usdt_prices,
        transaction_cost_bps=10.0,
        start=start,
    )

    assert frame["turnover"].iloc[0] == pytest.approx(1.0)
    assert frame["trading_cost"].iloc[0] == pytest.approx(0.001)
    assert frame["strategy_return"].iloc[0] == pytest.approx(frame["asset_return"].iloc[0] - 0.001)
