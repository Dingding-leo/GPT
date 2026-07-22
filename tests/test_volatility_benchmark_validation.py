from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from gpt_quant.benchmarks import (
    simple_trend_long_cash_frame,
    volatility_targeted_long_frame,
)


@pytest.mark.parametrize(
    "target_volatility",
    [math.nan, math.inf, -math.inf, 0.0, -0.1, True],
    ids=[
        "nan",
        "positive-infinity",
        "negative-infinity",
        "zero",
        "negative",
        "boolean",
    ],
)
def test_volatility_benchmark_rejects_invalid_target_volatility(
    btc_usdt_prices: pd.Series,
    target_volatility: float | bool,
) -> None:
    with pytest.raises(ValueError, match="target_volatility must be finite and positive"):
        volatility_targeted_long_frame(
            btc_usdt_prices.iloc[:250],
            target_volatility=target_volatility,
        )


@pytest.mark.parametrize(
    "annualization",
    [math.nan, math.inf, -math.inf, 0, 1, -1, 365.5, True],
    ids=[
        "nan",
        "positive-infinity",
        "negative-infinity",
        "zero",
        "one",
        "negative",
        "fractional",
        "boolean",
    ],
)
def test_volatility_benchmark_rejects_invalid_annualization(
    btc_usdt_prices: pd.Series,
    annualization: float | int | bool,
) -> None:
    with pytest.raises(ValueError, match="annualization must be an integer at least 2"):
        volatility_targeted_long_frame(
            btc_usdt_prices.iloc[:250],
            annualization=annualization,
        )


@pytest.mark.parametrize(
    "volatility_lookback",
    [math.nan, math.inf, -math.inf, 0, 1, -1, 20.5, True],
    ids=[
        "nan",
        "positive-infinity",
        "negative-infinity",
        "zero",
        "one",
        "negative",
        "fractional",
        "boolean",
    ],
)
def test_volatility_benchmark_rejects_invalid_lookback(
    btc_usdt_prices: pd.Series,
    volatility_lookback: float | int | bool,
) -> None:
    with pytest.raises(
        ValueError,
        match="volatility_lookback must be an integer at least 2",
    ):
        volatility_targeted_long_frame(
            btc_usdt_prices.iloc[:250],
            volatility_lookback=volatility_lookback,
        )


@pytest.mark.parametrize(
    "lookback",
    [math.nan, math.inf, -math.inf, 0, -1, 20.5, True],
    ids=[
        "nan",
        "positive-infinity",
        "negative-infinity",
        "zero",
        "negative-future-period",
        "fractional",
        "boolean",
    ],
)
def test_simple_trend_benchmark_rejects_invalid_lookback(
    btc_usdt_prices: pd.Series,
    lookback: float | int | bool,
) -> None:
    with pytest.raises(ValueError, match="lookback must be an integer at least 1"):
        simple_trend_long_cash_frame(
            btc_usdt_prices.iloc[:250],
            lookback=lookback,
        )


def test_valid_volatility_benchmark_preserves_declared_position_formula(
    btc_usdt_prices: pd.Series,
) -> None:
    prices = btc_usdt_prices.iloc[:250]
    volatility_lookback = 20
    target_volatility = 0.40
    max_position = 0.75
    annualization = 365

    frame = volatility_targeted_long_frame(
        prices,
        volatility_lookback=volatility_lookback,
        target_volatility=target_volatility,
        max_position=max_position,
        annualization=annualization,
    )
    log_returns = np.log(prices).diff()
    realized = log_returns.rolling(
        volatility_lookback,
        min_periods=volatility_lookback,
    ).std(ddof=0) * np.sqrt(annualization)
    expected_position = (
        (target_volatility / realized.replace(0.0, np.nan))
        .clip(0.0, max_position)
        .shift(1)
        .fillna(0.0)
        .rename("position")
    )

    pd.testing.assert_series_equal(frame["position"], expected_position)
    assert frame["position"].gt(0.0).any()


def test_valid_simple_trend_benchmark_preserves_declared_position_formula(
    btc_usdt_prices: pd.Series,
) -> None:
    prices = btc_usdt_prices.iloc[:250]
    lookback = 20

    frame = simple_trend_long_cash_frame(prices, lookback=lookback)
    expected_position = (
        (prices.pct_change(lookback) > 0.0).astype(float).shift(1).fillna(0.0).rename("position")
    )

    pd.testing.assert_series_equal(frame["position"], expected_position)
    assert frame["position"].eq(0.0).any()
    assert frame["position"].eq(1.0).any()
