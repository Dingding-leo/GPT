from __future__ import annotations

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .data import validate_prices


def build_target_position(prices: pd.Series, config: StrategyConfig) -> pd.Series:
    """Build the close-to-close target position using information through time t.

    The backtester must lag this target by one bar before applying it to returns.
    """

    clean = validate_prices(prices)
    log_returns = np.log(clean).diff()

    trend_mean = log_returns.rolling(
        config.momentum_lookback,
        min_periods=config.momentum_lookback,
    ).mean()
    trend_std = log_returns.rolling(
        config.momentum_lookback,
        min_periods=config.momentum_lookback,
    ).std(ddof=0)
    trend_score = trend_mean / trend_std.replace(0.0, np.nan) * np.sqrt(config.momentum_lookback)

    recent_return = log_returns.rolling(
        config.reversal_lookback,
        min_periods=config.reversal_lookback,
    ).sum()
    risk_scale = log_returns.rolling(
        config.volatility_lookback,
        min_periods=config.volatility_lookback,
    ).std(ddof=0)
    reversal_score = -recent_return / (
        risk_scale.replace(0.0, np.nan) * np.sqrt(config.reversal_lookback)
    )

    trend_weight, reversal_weight = config.normalized_weights()
    ensemble_score = (trend_weight * trend_score + reversal_weight * reversal_score).clip(-4.0, 4.0)
    directional_signal = pd.Series(
        np.tanh(ensemble_score.to_numpy()),
        index=ensemble_score.index,
        name="directional_signal",
    )

    realized_volatility = log_returns.rolling(
        config.volatility_lookback,
        min_periods=config.volatility_lookback,
    ).std(ddof=0) * np.sqrt(config.annualization)
    volatility_scalar = (config.target_volatility / realized_volatility.replace(0.0, np.nan)).clip(
        lower=0.0, upper=config.max_abs_position
    )

    target = (directional_signal * volatility_scalar).clip(
        config.min_position,
        config.max_abs_position,
    )
    return target.replace([np.inf, -np.inf], np.nan).fillna(0.0).rename("target_position")
