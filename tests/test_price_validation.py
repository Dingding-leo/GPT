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


def test_validate_prices_localizes_naive_real_index_to_utc(
    btc_usdt_prices: pd.Series,
) -> None:
    prices = _real_price_window(btc_usdt_prices)
    prices.index = prices.index.tz_localize(None)

    validated = validate_prices(prices)

    expected = prices.copy()
    expected.index = expected.index.tz_localize("UTC")
    pd.testing.assert_series_equal(validated, expected)


def test_validate_prices_converts_aware_real_index_to_utc_without_changing_instants(
    btc_usdt_prices: pd.Series,
) -> None:
    expected = _real_price_window(btc_usdt_prices)
    prices = expected.copy()
    prices.index = prices.index.tz_convert("Australia/Adelaide")

    validated = validate_prices(prices)

    pd.testing.assert_series_equal(validated, expected)


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


def test_load_price_csv_rejects_duplicate_instants_after_utc_normalization(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    prices = _real_price_window(btc_usdt_prices)
    frame = prices.rename_axis("timestamp").reset_index()
    frame["timestamp"] = [timestamp.isoformat() for timestamp in prices.index]
    duplicate_instant = prices.index[9].tz_convert("Australia/Adelaide").isoformat()
    frame.loc[10, "timestamp"] = duplicate_instant

    assert frame.loc[9, "timestamp"] != frame.loc[10, "timestamp"]
    normalized = pd.to_datetime(frame.loc[[9, 10], "timestamp"], utc=True)
    assert normalized.iloc[0] == normalized.iloc[1]

    path = tmp_path / "utc-normalized-duplicate-okx-prices.csv"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="price index must not contain duplicates"):
        load_price_csv(path)
