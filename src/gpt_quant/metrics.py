from __future__ import annotations

import math
from collections.abc import Mapping
from numbers import Number

import numpy as np
import pandas as pd

from .backtest import BacktestResult

_POSITION_EPSILON = 1e-12


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


def _position_activity_metrics(
    frame: pd.DataFrame,
    returns: pd.Series,
    *,
    annualization: int,
    turnover: pd.Series,
    exchange_fee_sum: float,
) -> dict[str, float | int]:
    """Measure frame-local target-position activity without claiming broker executions."""

    if "position" not in frame:
        return {
            "target_position_turnover_sum": 0.0,
            "target_position_rebalance_count": 0,
            "annualized_target_position_rebalance_count": 0.0,
            "position_entry_count": 0,
            "position_exit_count": 0,
            "position_episode_count": 0,
            "annualized_position_episode_count": 0.0,
            "completed_position_episode_count": 0,
            "open_position_episode_count": 0,
            "active_bar_count": 0,
            "active_bar_ratio": 0.0,
            "mean_completed_holding_bars": 0.0,
            "median_completed_holding_bars": 0.0,
            "max_completed_holding_bars": 0,
            "current_holding_bars": 0,
            "completed_episode_win_count": 0,
            "completed_episode_loss_count": 0,
            "completed_episode_flat_count": 0,
            "completed_episode_hit_rate": 0.0,
            "completed_episode_profit_factor": 0.0,
            "completed_episode_profit_factor_defined": 0,
            "average_turnover_per_rebalance": 0.0,
            "exchange_fee_per_rebalance": 0.0,
        }

    position = (
        pd.to_numeric(frame["position"], errors="coerce")
        .fillna(0.0)
        .astype(float)
    )
    active = position.abs() > _POSITION_EPSILON
    previous_active = active.shift(1, fill_value=False)
    entries = active & ~previous_active
    exits = ~active & previous_active
    rebalances = turnover > _POSITION_EPSILON

    completed_returns: list[float] = []
    completed_holding_bars: list[int] = []
    in_episode = False
    episode_growth = 1.0
    episode_holding_bars = 0

    for is_active, is_entry, is_exit, strategy_return in zip(
        active.to_numpy(copy=False),
        entries.to_numpy(copy=False),
        exits.to_numpy(copy=False),
        returns.to_numpy(copy=False),
        strict=True,
    ):
        if is_entry:
            if in_episode:
                raise RuntimeError(
                    "position episode tracking entered an invalid nested state"
                )
            in_episode = True
            episode_growth = 1.0
            episode_holding_bars = 0

        if not in_episode:
            continue

        episode_growth *= 1.0 + float(strategy_return)
        if is_active:
            episode_holding_bars += 1
        if is_exit:
            completed_returns.append(episode_growth - 1.0)
            completed_holding_bars.append(episode_holding_bars)
            in_episode = False

    completed_count = len(completed_returns)
    win_count = sum(value > 0.0 for value in completed_returns)
    loss_count = sum(value < 0.0 for value in completed_returns)
    flat_count = completed_count - win_count - loss_count
    gross_episode_profit = sum(value for value in completed_returns if value > 0.0)
    gross_episode_loss = -sum(value for value in completed_returns if value < 0.0)
    profit_factor_defined = int(gross_episode_loss > 0.0)
    profit_factor = (
        gross_episode_profit / gross_episode_loss if profit_factor_defined else 0.0
    )

    rebalance_count = int(rebalances.sum())
    total_turnover = float(turnover.sum())
    active_bar_count = int(active.sum())

    return {
        "target_position_turnover_sum": total_turnover,
        "target_position_rebalance_count": rebalance_count,
        "annualized_target_position_rebalance_count": (
            rebalance_count / len(frame) * annualization
        ),
        "position_entry_count": int(entries.sum()),
        "position_exit_count": int(exits.sum()),
        "position_episode_count": int(entries.sum()),
        "annualized_position_episode_count": (
            int(entries.sum()) / len(frame) * annualization
        ),
        "completed_position_episode_count": completed_count,
        "open_position_episode_count": int(in_episode),
        "active_bar_count": active_bar_count,
        "active_bar_ratio": active_bar_count / len(frame),
        "mean_completed_holding_bars": (
            float(np.mean(completed_holding_bars)) if completed_holding_bars else 0.0
        ),
        "median_completed_holding_bars": (
            float(np.median(completed_holding_bars)) if completed_holding_bars else 0.0
        ),
        "max_completed_holding_bars": (
            max(completed_holding_bars) if completed_holding_bars else 0
        ),
        "current_holding_bars": episode_holding_bars if in_episode else 0,
        "completed_episode_win_count": win_count,
        "completed_episode_loss_count": loss_count,
        "completed_episode_flat_count": flat_count,
        "completed_episode_hit_rate": (
            win_count / completed_count if completed_count else 0.0
        ),
        "completed_episode_profit_factor": profit_factor,
        "completed_episode_profit_factor_defined": profit_factor_defined,
        "average_turnover_per_rebalance": (
            total_turnover / rebalance_count if rebalance_count else 0.0
        ),
        "exchange_fee_per_rebalance": (
            exchange_fee_sum / rebalance_count if rebalance_count else 0.0
        ),
    }


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

    turnover_series = (
        pd.to_numeric(frame["turnover"], errors="coerce").fillna(0.0).astype(float)
        if "turnover" in frame
        else pd.Series(0.0, index=frame.index, name="turnover")
    )
    turnover = float(turnover_series.mean()) * ann
    position_series = (
        pd.to_numeric(frame["position"], errors="coerce").fillna(0.0).astype(float)
        if "position" in frame
        else pd.Series(0.0, index=frame.index, name="position")
    )
    exposure = float(position_series.abs().mean()) if "position" in frame else 0.0
    trading_cost_series = (
        pd.to_numeric(frame["trading_cost"], errors="coerce").fillna(0.0).astype(float)
        if "trading_cost" in frame
        else pd.Series(0.0, index=frame.index, name="trading_cost")
    )
    cost_drag = float(trading_cost_series.sum())

    nonzero_returns = returns[returns != 0.0]
    hit_rate = float((nonzero_returns > 0.0).mean()) if len(nonzero_returns) else 0.0
    active_mask = position_series.abs() > _POSITION_EPSILON
    active_bar_returns = returns[active_mask]
    bar_hit_rate = (
        float((active_bar_returns > 0.0).mean()) if len(active_bar_returns) else 0.0
    )
    activity = _position_activity_metrics(
        frame,
        returns,
        annualization=ann,
        turnover=turnover_series,
        exchange_fee_sum=cost_drag,
    )

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
        "bar_hit_rate": bar_hit_rate,
        **activity,
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
            raise ValueError(
                "strategy_return must equal gross_strategy_return minus trading_cost"
            )

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
