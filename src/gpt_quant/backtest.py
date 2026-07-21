from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import StrategyConfig
from .data import validate_prices
from .features import build_target_position


@dataclass(frozen=True, slots=True)
class BacktestResult:
    frame: pd.DataFrame
    config: StrategyConfig


def run_backtest(
    prices: pd.Series,
    config: StrategyConfig,
    *,
    start: pd.Timestamp | str | None = None,
    end: pd.Timestamp | str | None = None,
) -> BacktestResult:
    """Run a one-bar-delayed, transaction-cost-aware close-to-close backtest."""

    clean = validate_prices(prices)
    target_position = build_target_position(clean, config)

    # A target calculated at close t can only earn return t -> t+1.
    position = target_position.shift(1).fillna(0.0).rename("position")
    asset_return = clean.pct_change().fillna(0.0).rename("asset_return")
    turnover = position.diff().abs().fillna(position.abs()).rename("turnover")
    trading_cost = (turnover * config.transaction_cost_bps / 10_000.0).rename("trading_cost")
    strategy_return = (position * asset_return - trading_cost).rename("strategy_return")

    frame = pd.concat(
        [
            clean.rename("close"),
            asset_return,
            target_position,
            position,
            turnover,
            trading_cost,
            strategy_return,
        ],
        axis=1,
    )
    frame["nav"] = (1.0 + frame["strategy_return"]).cumprod()

    if start is not None or end is not None:
        frame = frame.loc[start:end].copy()
        if frame.empty:
            raise ValueError("requested backtest window is empty")
        frame["nav"] = (1.0 + frame["strategy_return"]).cumprod()

    return BacktestResult(frame=frame, config=config)
