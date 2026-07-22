from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import load_price_csv, validate_prices


def _real_price_window(btc_usdt_prices: pd.Series) -> pd.Series:
    return btc_usdt_prices.iloc[:60].copy()


def test_validate_prices_preserves_valid_real_series(btc_usdt_prices: pd.Series) -> None:
    prices = _real_price_window(btc_usdt_prices)

    validated = validate_prices(prices)

    pd.testing.assert_series_equal(validated, prices)


@pytest.mark.parametrize(
    "bad_value",
    [math.nan, math.inf, -math.inf, "not-a-number"],
    ids=["nan", "positive-infinity", "negative-infinity", "non-numeric"],
)
def test_validate_prices_rejects_invalid_observations(
    btc_usdt_prices: pd.Series,
    bad_value: object,
) -> None:
    corrupted = _real_price_window(btc_usdt_prices).astype(object)
    corrupted.iloc[10] = bad_value

    with pytest.raises(ValueError, match="prices must contain only finite numeric values"):
        validate_prices(corrupted)


def test_validate_prices_rejects_duplicate_timestamps(btc_usdt_prices: pd.Series) -> None:
    corrupted = _real_price_window(btc_usdt_prices)
    timestamps = list(corrupted.index)
    timestamps[10] = timestamps[9]
    corrupted.index = pd.DatetimeIndex(timestamps)

    with pytest.raises(ValueError, match="price index must not contain duplicates"):
        validate_prices(corrupted)


def test_validate_prices_rejects_non_monotonic_timestamps(
    btc_usdt_prices: pd.Series,
) -> None:
    prices = _real_price_window(btc_usdt_prices)
    order = list(range(len(prices)))
    order[10], order[11] = order[11], order[10]
    corrupted = prices.iloc[order]

    with pytest.raises(ValueError, match="price index must be strictly increasing"):
        validate_prices(corrupted)


def test_load_price_csv_rejects_invalid_timestamp(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    frame = _real_price_window(btc_usdt_prices).rename_axis("timestamp").reset_index()
    frame["timestamp"] = frame["timestamp"].astype(str)
    frame.loc[10, "timestamp"] = "not-a-timestamp"
    path = tmp_path / "corrupted-real-okx-prices.csv"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="timestamp column must contain only valid timestamps"):
        load_price_csv(path)
