from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from gpt_quant.metrics import performance_metrics


def _real_return_frame(prices: pd.Series) -> pd.DataFrame:
    returns = prices.pct_change().dropna().iloc[:30]
    return pd.DataFrame(
        {
            "strategy_return": returns,
            "position": 1.0,
            "turnover": 0.0,
            "trading_cost": 0.0,
        },
        index=returns.index,
    )


@pytest.mark.parametrize(
    "invalid_value",
    [np.nan, np.inf, -np.inf, "not-a-return", True, 0.01 + 0.02j],
)
def test_performance_metrics_rejects_invalid_primary_returns(
    btc_usdt_prices: pd.Series,
    invalid_value: object,
) -> None:
    frame = _real_return_frame(btc_usdt_prices)
    if isinstance(invalid_value, str | bool | complex):
        frame["strategy_return"] = frame["strategy_return"].astype(object)
    frame.iat[-1, frame.columns.get_loc("strategy_return")] = invalid_value

    with pytest.raises(ValueError, match="strategy_return must contain finite real numbers"):
        performance_metrics(frame, annualization=365)


def test_performance_metrics_accepts_object_backed_real_numbers(
    btc_usdt_prices: pd.Series,
) -> None:
    frame = _real_return_frame(btc_usdt_prices)
    expected = performance_metrics(frame, annualization=365)
    frame["strategy_return"] = frame["strategy_return"].astype(object)

    assert performance_metrics(frame, annualization=365) == expected
