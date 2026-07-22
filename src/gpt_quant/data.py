from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def validate_prices(prices: pd.Series, *, minimum_rows: int = 50) -> pd.Series:
    """Return a validated, strictly positive, chronologically ordered price series."""

    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be a pandas Series")
    if len(prices) < minimum_rows:
        raise ValueError(f"prices must contain at least {minimum_rows} rows")

    numeric = pd.to_numeric(prices, errors="coerce")
    if numeric.isna().any():
        raise ValueError("prices must contain only finite numeric values")
    clean = numeric.astype(float)
    if not np.isfinite(clean.to_numpy()).all():
        raise ValueError("prices must contain only finite numeric values")

    if not isinstance(clean.index, pd.DatetimeIndex):
        try:
            clean.index = pd.to_datetime(clean.index, utc=True, errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError("price index must be datetime-like") from exc
    if clean.index.hasnans:
        raise ValueError("price index must not contain missing timestamps")
    if clean.index.has_duplicates:
        raise ValueError("price index must not contain duplicates")
    if not clean.index.is_monotonic_increasing:
        raise ValueError("price index must be strictly increasing")
    if (clean <= 0).any():
        raise ValueError("prices must be strictly positive")

    clean.name = prices.name or "close"
    return clean


def load_price_csv(
    path: str | Path,
    *,
    timestamp_col: str = "timestamp",
    close_col: str = "close",
) -> pd.Series:
    """Load a timestamp/close CSV without assuming a vendor-specific schema."""

    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    frame = pd.read_csv(csv_path)
    missing = {timestamp_col, close_col}.difference(frame.columns)
    if missing:
        raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

    index = pd.to_datetime(frame[timestamp_col], utc=True, errors="coerce")
    if index.isna().any():
        raise ValueError("timestamp column must contain only valid timestamps")
    series = pd.Series(frame[close_col].to_numpy(), index=index, name="close")
    return validate_prices(series)
