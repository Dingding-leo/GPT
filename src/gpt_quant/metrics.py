from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

from .backtest import BacktestResult


def max_drawdown_from_returns(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").fillna(0.0).astype(float)
    if clean.empty:
        return 0.0

    # Include initial capital so a loss on the first observation is measured
    # against the true starting peak rather than treated as a zero drawdown.
    nav = np.concatenate(([1.0], np.cumprod(1.0 + clean.to_numpy())))
    running_peak = np.maximum.accumulate(nav)
    drawdown = nav / running_peak - 1.0
    return float(drawdown.min())


def performance_metrics(
    result: BacktestResult | pd.DataFrame,
    *,
    annualization: int | None = None,
) -> dict[str, float | int]:
    frame = result.frame if isinstance(result, BacktestResult) else result
    if "strategy_return" not in frame:
        raise ValueError("frame must contain strategy_return")

    ann = annualization or (
        result.config.annualization if isinstance(result, BacktestResult) else 252
    )
    returns = pd.to_numeric(frame["strategy_return"], errors="coerce").fillna(0.0)
    n = int(len(returns))
    if n == 0:
        raise ValueError("cannot calculate metrics for an empty frame")

    total_growth = float((1.0 + returns).prod())
    total_return = total_growth - 1.0
    years = n / ann
    cagr = total_growth ** (1.0 / years) - 1.0 if total_growth > 0 else -1.0

    daily_mean = float(returns.mean())
    daily_std = float(returns.std(ddof=0))
    annualized_volatility = daily_std * math.sqrt(ann)
    sharpe = daily_mean / daily_std * math.sqrt(ann) if daily_std > 0 else 0.0

    downside = returns.clip(upper=0.0)
    downside_std = float(np.sqrt(np.mean(np.square(downside))))
    sortino = daily_mean / downside_std * math.sqrt(ann) if downside_std > 0 else 0.0

    max_drawdown = max_drawdown_from_returns(returns)
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0 else 0.0

    turnover = (
        float(pd.to_numeric(frame["turnover"], errors="coerce").fillna(0.0).mean()) * ann
        if "turnover" in frame
        else 0.0
    )
    exposure = (
        float(pd.to_numeric(frame["position"], errors="coerce").fillna(0.0).abs().mean())
        if "position" in frame
        else 0.0
    )
    cost_drag = (
        float(pd.to_numeric(frame["trading_cost"], errors="coerce").fillna(0.0).sum())
        if "trading_cost" in frame
        else 0.0
    )

    active_returns = returns[returns != 0.0]
    hit_rate = float((active_returns > 0.0).mean()) if len(active_returns) else 0.0

    values: Mapping[str, float | int] = {
        "observations": n,
        "total_return": total_return,
        "cagr": cagr,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "annualized_turnover": turnover,
        "average_abs_exposure": exposure,
        "cost_drag_sum": cost_drag,
        "hit_rate": hit_rate,
    }
    return {
        key: int(value) if isinstance(value, int) else float(value) for key, value in values.items()
    }
