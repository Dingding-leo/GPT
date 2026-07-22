from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np
import pandas as pd

from .data import validate_prices


def _validate_transaction_cost_bps(transaction_cost_bps: float) -> None:
    if not math.isfinite(transaction_cost_bps) or transaction_cost_bps < 0:
        raise ValueError("transaction_cost_bps must be finite and non-negative")


def _validate_max_position(max_position: float) -> None:
    if not math.isfinite(max_position) or max_position <= 0:
        raise ValueError("max_position must be finite and positive")


def _validate_volatility_lookback(volatility_lookback: int) -> None:
    if (
        isinstance(volatility_lookback, bool)
        or not isinstance(volatility_lookback, Integral)
        or volatility_lookback < 2
    ):
        raise ValueError("volatility_lookback must be an integer at least 2")


def _validate_trend_lookback(lookback: int) -> None:
    if isinstance(lookback, bool) or not isinstance(lookback, Integral) or lookback < 1:
        raise ValueError("lookback must be an integer at least 1")


def _validate_target_volatility(target_volatility: float) -> None:
    if (
        isinstance(target_volatility, bool)
        or not isinstance(target_volatility, Real)
        or not math.isfinite(target_volatility)
        or target_volatility <= 0
    ):
        raise ValueError("target_volatility must be finite and positive")


def _validate_annualization(annualization: int) -> None:
    if (
        isinstance(annualization, bool)
        or not isinstance(annualization, Integral)
        or annualization < 2
    ):
        raise ValueError("annualization must be an integer at least 2")


def _build_frame(
    prices: pd.Series,
    position: pd.Series,
    *,
    transaction_cost_bps: float,
    start: pd.Timestamp | str | None,
    end: pd.Timestamp | str | None,
    initial_position: float = 0.0,
) -> pd.DataFrame:
    _validate_transaction_cost_bps(transaction_cost_bps)
    clean = validate_prices(prices)
    aligned_position = position.reindex(clean.index).fillna(0.0).astype(float)
    asset_return = clean.pct_change().fillna(0.0).rename("asset_return")
    turnover = aligned_position.diff().abs().fillna(aligned_position.abs()).rename("turnover")
    trading_cost = (turnover * transaction_cost_bps / 10_000.0).rename("trading_cost")
    strategy_return = (aligned_position * asset_return - trading_cost).rename("strategy_return")
    frame = pd.concat(
        [
            clean.rename("close"),
            asset_return,
            aligned_position.rename("position"),
            turnover,
            trading_cost,
            strategy_return,
        ],
        axis=1,
    )
    if start is not None or end is not None:
        frame = frame.loc[start:end].copy()
    if frame.empty:
        raise ValueError("requested benchmark window is empty")

    # Every reported benchmark starts from the same cash state as the strategy.
    # Recompute the first row after slicing so entry turnover is not inherited
    # from pre-evaluation history.
    first = frame.index[0]
    entry_turnover = abs(float(frame.at[first, "position"]) - initial_position)
    frame.at[first, "turnover"] = entry_turnover
    frame.at[first, "trading_cost"] = entry_turnover * transaction_cost_bps / 10_000.0
    frame.at[first, "strategy_return"] = float(frame.at[first, "position"]) * float(
        frame.at[first, "asset_return"]
    ) - float(frame.at[first, "trading_cost"])
    frame["nav"] = (1.0 + frame["strategy_return"]).cumprod()
    return frame


def buy_and_hold_frame(
    prices: pd.Series,
    *,
    transaction_cost_bps: float = 0.0,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    clean = validate_prices(prices)
    position = pd.Series(1.0, index=clean.index)
    return _build_frame(
        clean,
        position,
        transaction_cost_bps=transaction_cost_bps,
        start=start,
        end=end,
    )


def volatility_targeted_long_frame(
    prices: pd.Series,
    *,
    volatility_lookback: int = 30,
    target_volatility: float = 0.50,
    max_position: float = 1.0,
    annualization: int = 365,
    transaction_cost_bps: float = 0.0,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    _validate_volatility_lookback(volatility_lookback)
    _validate_target_volatility(target_volatility)
    _validate_max_position(max_position)
    _validate_annualization(annualization)
    clean = validate_prices(prices)
    log_returns = np.log(clean).diff()
    realized = log_returns.rolling(
        volatility_lookback,
        min_periods=volatility_lookback,
    ).std(ddof=0) * np.sqrt(annualization)
    target = (target_volatility / realized.replace(0.0, np.nan)).clip(0.0, max_position)
    position = target.shift(1).fillna(0.0)
    return _build_frame(
        clean,
        position,
        transaction_cost_bps=transaction_cost_bps,
        start=start,
        end=end,
    )


def simple_trend_long_cash_frame(
    prices: pd.Series,
    *,
    lookback: int = 180,
    transaction_cost_bps: float = 0.0,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    _validate_trend_lookback(lookback)
    clean = validate_prices(prices)
    trailing_return = clean.pct_change(lookback)
    target = (trailing_return > 0.0).astype(float)
    position = target.shift(1).fillna(0.0)
    return _build_frame(
        clean,
        position,
        transaction_cost_bps=transaction_cost_bps,
        start=start,
        end=end,
    )
