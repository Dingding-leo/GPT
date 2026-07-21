from __future__ import annotations

import pytest

from gpt_quant import generate_regime_prices
from gpt_quant.benchmarks import buy_and_hold_frame


def test_buy_and_hold_charges_entry_cost_at_evaluation_start() -> None:
    prices = generate_regime_prices(rows=700, seed=31)
    start = prices.index[500]
    frame = buy_and_hold_frame(
        prices,
        transaction_cost_bps=10.0,
        start=start,
    )

    assert frame["turnover"].iloc[0] == pytest.approx(1.0)
    assert frame["trading_cost"].iloc[0] == pytest.approx(0.001)
    assert frame["strategy_return"].iloc[0] == pytest.approx(frame["asset_return"].iloc[0] - 0.001)
