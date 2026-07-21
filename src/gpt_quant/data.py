from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .reproducibility import file_sha256


@dataclass(frozen=True, slots=True)
class VerifiedPriceSnapshot:
    """A validated price series bound to immutable source metadata."""

    prices: pd.Series
    metadata: dict[str, Any]


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


def _required_text(values: dict[str, Any], key: str, *, context: str) -> str:
    value = str(values.get(key, "")).strip()
    if not value:
        raise ValueError(f"{context} must contain non-empty {key!r}")
    return value


def load_verified_price_snapshot(manifest_path: str | Path) -> VerifiedPriceSnapshot:
    """Load real-market CSV parts only after verifying their manifest and hashes."""

    manifest = Path(manifest_path)
    if not manifest.exists():
        raise FileNotFoundError(manifest)
    with manifest.open("r", encoding="utf-8") as handle:
        metadata = json.load(handle)
    if not isinstance(metadata, dict):
        raise ValueError("snapshot manifest must be a JSON object")

    _required_text(metadata, "provider", context="snapshot manifest")
    _required_text(metadata, "instrument_id", context="snapshot manifest")
    _required_text(metadata, "bar", context="snapshot manifest")
    timestamp_col = _required_text(metadata, "timestamp_col", context="snapshot manifest")
    close_col = _required_text(metadata, "close_col", context="snapshot manifest")
    files = metadata.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("snapshot manifest must contain a non-empty files list")

    frames: list[pd.DataFrame] = []
    for position, entry in enumerate(files, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"snapshot file entry {position} must be an object")
        context = f"snapshot file entry {position}"
        relative_path = Path(_required_text(entry, "path", context=context))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("snapshot file paths must stay inside the manifest directory")
        csv_path = manifest.parent / relative_path
        if not csv_path.exists():
            raise FileNotFoundError(csv_path)
        expected_hash = _required_text(entry, "sha256", context=context).lower()
        actual_hash = file_sha256(csv_path)
        if actual_hash != expected_hash:
            raise ValueError(
                f"snapshot SHA-256 mismatch for {relative_path}: "
                f"expected {expected_hash}, actual {actual_hash}"
            )
        frames.append(pd.read_csv(csv_path))

    frame = pd.concat(frames, ignore_index=True)
    missing = {timestamp_col, close_col}.difference(frame.columns)
    if missing:
        raise ValueError(f"snapshot CSV is missing required columns: {sorted(missing)}")
    index = pd.to_datetime(frame[timestamp_col], utc=True, errors="coerce")
    prices = pd.Series(frame[close_col].to_numpy(), index=index, name="close")
    prices = validate_prices(prices[~prices.index.isna()])

    expected_rows = int(metadata.get("observations", 0))
    if expected_rows != len(prices):
        raise ValueError(
            f"snapshot observation mismatch: expected {expected_rows}, actual {len(prices)}"
        )
    expected_start = pd.Timestamp(
        _required_text(metadata, "start", context="snapshot manifest")
    )
    expected_end = pd.Timestamp(_required_text(metadata, "end", context="snapshot manifest"))
    if prices.index[0] != expected_start or prices.index[-1] != expected_end:
        raise ValueError("snapshot timestamps do not match manifest start/end")

    return VerifiedPriceSnapshot(prices=prices, metadata=dict(metadata))
