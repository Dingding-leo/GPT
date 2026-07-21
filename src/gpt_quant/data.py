from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def validate_prices(prices: pd.Series, *, minimum_rows: int = 50) -> pd.Series:
    """Return a clean, strictly positive, time-ordered price series."""

    if not isinstance(prices, pd.Series):
        raise TypeError("prices must be a pandas Series")
    if len(prices) < minimum_rows:
        raise ValueError(f"prices must contain at least {minimum_rows} rows")

    clean = pd.to_numeric(prices, errors="coerce").dropna().astype(float)
    if not isinstance(clean.index, pd.DatetimeIndex):
        try:
            clean.index = pd.to_datetime(clean.index, utc=True)
        except (TypeError, ValueError) as exc:
            raise ValueError("price index must be datetime-like") from exc

    clean = clean[~clean.index.duplicated(keep="last")].sort_index()
    if len(clean) < minimum_rows:
        raise ValueError(f"prices must contain at least {minimum_rows} valid rows")
    if not np.isfinite(clean.to_numpy()).all():
        raise ValueError("prices contain non-finite values")
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
    series = pd.Series(frame[close_col].to_numpy(), index=index, name="close")
    series = series[~series.index.isna()]
    return validate_prices(series)
