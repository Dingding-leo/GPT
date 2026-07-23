from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Number

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


def _invalid_return_error(series: pd.Series, position: int, *, label: str) -> ValueError:
    index_value = series.index[position]
    location = (
        index_value.isoformat() if isinstance(index_value, pd.Timestamp) else str(index_value)
    )
    return ValueError(f"{label} must contain finite real numbers; invalid value at {location}")


def _validated_returns(series: pd.Series, *, label: str = "strategy_return") -> pd.Series:
    values = series.to_numpy(copy=False)
    kind = values.dtype.kind

    if kind in "iuf":
        float_values = values.astype(float, copy=False)
    elif kind == "O":
        for position, value in enumerate(values):
            if not isinstance(value, Number) or isinstance(
                value, bool | np.bool_ | complex | np.complexfloating
            ):
                raise _invalid_return_error(series, position, label=label)
        float_values = np.asarray(values, dtype=float)
    else:
        raise _invalid_return_error(series, 0, label=label)

    invalid_positions = np.flatnonzero(~np.isfinite(float_values))
    if invalid_positions.size:
        raise _invalid_return_error(series, int(invalid_positions[0]), label=label)
    return pd.Series(float_values, index=series.index, name=series.name, copy=False)


def _validate_solvent_returns(returns: pd.Series) -> None:
    insolvent = returns <= -1.0
    if insolvent.any():
        first = insolvent[insolvent].index[0]
        location = first.isoformat() if isinstance(first, pd.Timestamp) else str(first)
        raise ValueError(
            f"strategy return must remain greater than -100%; insolvency occurs at {location}"
        )


def _compounded_return(returns: pd.Series) -> tuple[float, float]:
    growth = float((1.0 + returns).prod())
    return growth, growth - 1.0


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
    if frame.empty:
        raise ValueError("cannot calculate metrics for an empty frame")
    returns = _validated_returns(frame["strategy_return"])
    _validate_solvent_returns(returns)
    n = int(len(returns))

    total_growth, total_return = _compounded_return(returns)
    years = n / ann
    cagr = total_growth ** (1.0 / years) - 1.0 if total_growth > 0 else -1.0

    daily_mean = float(returns.mean())
    daily_std = float(returns.std(ddof=0))
    annualized_arithmetic_mean = daily_mean * ann
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

    values: dict[str, float | int] = {
        "observations": n,
        "total_return": total_return,
        "net_total_return": total_return,
        "cagr": cagr,
        "net_cagr": cagr,
        "annualized_arithmetic_mean": annualized_arithmetic_mean,
        "net_annualized_arithmetic_mean": annualized_arithmetic_mean,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "annualized_turnover": turnover,
        "average_abs_exposure": exposure,
        "cost_drag_sum": cost_drag,
        "exchange_fee_sum": cost_drag,
        "hit_rate": hit_rate,
    }

    if "gross_strategy_return" in frame:
        gross_returns = _validated_returns(
            frame["gross_strategy_return"],
            label="gross_strategy_return",
        )
        missing_gross_inputs = {"position", "asset_return"} - set(frame.columns)
        if missing_gross_inputs:
            raise ValueError("gross_strategy_return requires position and asset_return")
        position = _validated_returns(frame["position"], label="position")
        asset_returns = _validated_returns(frame["asset_return"], label="asset_return")
        expected_gross = position * asset_returns
        if not np.allclose(
            gross_returns.to_numpy(),
            expected_gross.to_numpy(),
            rtol=0.0,
            atol=1e-12,
        ):
            raise ValueError(
                "gross_strategy_return must equal position multiplied by asset_return"
            )
        if "trading_cost" not in frame:
            raise ValueError("gross_strategy_return requires trading_cost")
        trading_cost = _validated_returns(frame["trading_cost"], label="trading_cost")
        if (trading_cost < 0.0).any():
            raise ValueError("trading_cost must be non-negative")
        expected_net = gross_returns - trading_cost
        if not np.allclose(
            returns.to_numpy(),
            expected_net.to_numpy(),
            rtol=0.0,
            atol=1e-12,
        ):
            raise ValueError("strategy_return must equal gross_strategy_return minus trading_cost")

        gross_growth, gross_total_return = _compounded_return(gross_returns)
        gross_cagr = gross_growth ** (1.0 / years) - 1.0 if gross_growth > 0 else -1.0
        values.update(
            {
                "gross_total_return": gross_total_return,
                "gross_cagr": gross_cagr,
                "gross_annualized_arithmetic_mean": float(gross_returns.mean()) * ann,
                "compounded_exchange_fee_drag": gross_total_return - total_return,
            }
        )

    typed_values: Mapping[str, float | int] = values
    return {
        key: int(value) if isinstance(value, int) else float(value)
        for key, value in typed_values.items()
    }
