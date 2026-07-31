#!/usr/bin/env python3
"""Shared causal data and model utilities for the frozen experiment."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FEE = 0.0005
ANNUAL_HOURS = 24 * 365
PREFIX_ROWS = 43_441
TRAIN = (2_880, 17_520)
OOS = (17_520, 43_440)
FULL = (2_880, 43_440)
FOLD_HOURS = 2_160
BLOCK_HOURS = 168
TRAIN_WINDOW_HOURS = 17_520
RIDGE_ALPHA = 1e-4
MIN_TRAIN_ROWS = 60
HORIZONS = (24, 168)
DEFAULT_SEED = 20_260_731


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def find_csv(data_root: Path, instrument: str) -> Path:
    candidates = [
        data_root / instrument / "snapshot" / f"okx-{instrument}-1H.normalized.csv",
        data_root / instrument / "snapshot" / f"okx-{instrument}-1H.csv",
        data_root / instrument / "candles.csv",
        data_root / instrument / "full" / "candles.csv",
    ]
    for path in candidates:
        if path.is_file():
            return path
    matches = sorted(
        set(data_root.glob(f"**/okx-{instrument}-1H*.csv"))
        | set(data_root.glob(f"**/{instrument}/**/candles.csv"))
    )
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected exactly one candle CSV for {instrument}, got {matches}"
        )
    return matches[0]


def load_market(path: Path, instrument: str) -> dict[str, Any]:
    full = pd.read_csv(path)
    required = {"timestamp", "open", "close", "confirm"}
    if not required.issubset(full.columns):
        missing = sorted(required - set(full.columns))
        raise ValueError(f"{instrument}: missing columns {missing}")
    if len(full) < PREFIX_ROWS:
        raise ValueError(f"{instrument}: need {PREFIX_ROWS} rows, got {len(full)}")
    frame = full.iloc[:PREFIX_ROWS].copy()
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    expected = pd.date_range(
        timestamps.iloc[0], periods=PREFIX_ROWS, freq="h", tz="UTC"
    )
    if not np.array_equal(timestamps.array, expected.array):
        raise ValueError(f"{instrument}: frozen prefix is not contiguous 1H")
    if timestamps.iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError(f"{instrument}: unexpected start {timestamps.iloc[0]}")
    if timestamps.iloc[-1] != pd.Timestamp("2026-07-08T00:00:00Z"):
        raise ValueError(f"{instrument}: unexpected end {timestamps.iloc[-1]}")
    confirm = pd.to_numeric(frame["confirm"], errors="raise").to_numpy()
    if not np.all(confirm == 1):
        raise ValueError(f"{instrument}: incomplete bar in frozen prefix")
    opens = pd.to_numeric(frame["open"], errors="raise").to_numpy(float)
    closes = pd.to_numeric(frame["close"], errors="raise").to_numpy(float)
    if not np.all(np.isfinite(opens)) or np.any(opens <= 0):
        raise ValueError(f"{instrument}: invalid open")
    if not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        raise ValueError(f"{instrument}: invalid close")
    return {
        "timestamps": timestamps,
        "opens": opens,
        "closes": closes,
        "csv_path": str(path),
        "csv_sha256": sha256_file(path),
        "source_rows": int(len(full)),
    }


def rolling_rms(values: np.ndarray, window: int, *, downside: bool = False) -> np.ndarray:
    work = np.minimum(values, 0.0) if downside else values
    squared = np.square(work)
    prefix = np.r_[0.0, np.cumsum(squared)]
    out = np.full(values.size, np.nan)
    idx = np.arange(window - 1, values.size)
    sums = prefix[idx + 1] - prefix[idx + 1 - window]
    out[idx] = np.sqrt(sums / window)
    return out


def trailing_drawdown(closes: np.ndarray, window: int) -> np.ndarray:
    series = pd.Series(closes)
    peak = series.rolling(window=window, min_periods=window).max().to_numpy(float)
    return closes / peak - 1.0


def build_feature_matrix(market: dict[str, Any]) -> np.ndarray:
    closes = market["closes"]
    n = len(closes)
    log_close = np.log(closes)
    logret = np.full(n, np.nan)
    logret[1:] = np.diff(log_close)

    r24 = np.full(n, np.nan)
    r168 = np.full(n, np.nan)
    r720 = np.full(n, np.nan)
    r24[24:] = log_close[24:] - log_close[:-24]
    r168[168:] = log_close[168:] - log_close[:-168]
    r720[720:] = log_close[720:] - log_close[:-720]

    rms24 = np.full(n, np.nan)
    rms168 = np.full(n, np.nan)
    down24 = np.full(n, np.nan)
    down168 = np.full(n, np.nan)
    rms24[1:] = rolling_rms(logret[1:], 24)
    rms168[1:] = rolling_rms(logret[1:], 168)
    down24[1:] = rolling_rms(logret[1:], 24, downside=True)
    down168[1:] = rolling_rms(logret[1:], 168, downside=True)

    vol_ratio = np.full(n, np.nan)
    downside_ratio = np.full(n, np.nan)
    valid_vol = np.isfinite(rms24) & np.isfinite(rms168) & (rms168 > 0)
    valid_down = np.isfinite(down24) & np.isfinite(down168) & (down168 > 0)
    vol_ratio[valid_vol] = rms24[valid_vol] / rms168[valid_vol] - 1.0
    downside_ratio[valid_down] = down24[valid_down] / down168[valid_down] - 1.0
    drawdown168 = trailing_drawdown(closes, 168)

    features = np.column_stack(
        [r24, r168, r720, vol_ratio, downside_ratio, drawdown168]
    )
    if not np.all(np.isfinite(features[720:])):
        bad = np.argwhere(~np.isfinite(features[720:]))[:5]
        raise ValueError(f"non-finite features after warm-up at {bad.tolist()}")
    return features


def future_labels(opens: np.ndarray, horizon: int) -> np.ndarray:
    n = len(opens)
    labels = np.full(n, np.nan)
    last_signal = n - horizon - 2
    if last_signal >= 0:
        idx = np.arange(last_signal + 1)
        labels[idx] = np.log(opens[idx + 1 + horizon] / opens[idx + 1])
    return labels


def robust_ridge_predict(
    features: np.ndarray,
    labels: np.ndarray,
    train_indices: np.ndarray,
    decision_index: int,
) -> tuple[float, dict[str, Any]]:
    x_train = features[train_indices]
    y_train = labels[train_indices]
    valid = np.all(np.isfinite(x_train), axis=1) & np.isfinite(y_train)
    x_train = x_train[valid]
    y_train = y_train[valid]
    if len(y_train) < MIN_TRAIN_ROWS:
        return math.nan, {
            "rows": int(len(y_train)),
            "status": "insufficient_history",
        }

    location = np.median(x_train, axis=0)
    mad = np.median(np.abs(x_train - location), axis=0)
    zero_mad = (~np.isfinite(mad)) | (mad <= 0)
    scale = mad.copy()
    scale[zero_mad] = 1.0
    z_train = (x_train - location) / scale
    z_current = (features[decision_index] - location) / scale
    if not np.all(np.isfinite(z_train)) or not np.all(np.isfinite(z_current)):
        raise ValueError("non-finite robust-normalized feature")

    design = np.column_stack([np.ones(len(z_train)), z_train])
    penalty = np.eye(design.shape[1]) * RIDGE_ALPHA
    penalty[0, 0] = 0.0
    gram = design.T @ design + penalty
    rhs = design.T @ y_train
    beta = np.linalg.solve(gram, rhs)
    prediction = float(np.r_[1.0, z_current] @ beta)
    fitted = design @ beta
    residual = y_train - fitted
    return prediction, {
        "rows": int(len(y_train)),
        "status": "fit",
        "zero_mad_features": int(np.sum(zero_mad)),
        "residual_std": finite_or_none(float(np.std(residual, ddof=1))),
    }
