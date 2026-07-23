from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np
import pandas as pd

_POSITION_ADJUSTMENT_THRESHOLD = 1e-12
_MATERIAL_POSITION_ADJUSTMENT_THRESHOLD = 0.01
_ACTIVE_POSITION_THRESHOLD = 0.01
_POSITION_LIMIT_TOLERANCE = 1e-12
_DRAWDOWN_THRESHOLD = 1e-12
_EXPECTED_SHORTFALL_TAIL_FRACTION = 0.05


def _positive_integer(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return int(value)


def _finite_real(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label} must be a finite real number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{label} must be a finite real number")
    return parsed


def _finite_series(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame:
        raise ValueError(f"walk-forward diagnostics require {name}")
    try:
        values = pd.to_numeric(frame[name], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"walk-forward diagnostics require numeric {name}") from exc
    invalid = np.flatnonzero(~np.isfinite(values.to_numpy(copy=False)))
    if invalid.size:
        raise ValueError(f"walk-forward diagnostics require finite {name}")
    return values


def _underwater_durations(drawdown: np.ndarray) -> tuple[int, int]:
    longest = 0
    running = 0
    for value in drawdown:
        if value < -_DRAWDOWN_THRESHOLD:
            running += 1
            longest = max(longest, running)
        else:
            running = 0
    return (running if drawdown[-1] < -_DRAWDOWN_THRESHOLD else 0, longest)


def walk_forward_path_diagnostics(
    frame: pd.DataFrame,
    *,
    annualization: int,
    minimum_position: float,
    maximum_absolute_position: float,
) -> dict[str, float | int | str | bool]:
    """Reconstruct position-path diagnostics without treating transitions as exchange orders."""

    ann = _positive_integer(annualization, "annualization")
    minimum = _finite_real(minimum_position, "minimum_position")
    maximum = _finite_real(maximum_absolute_position, "maximum_absolute_position")
    if maximum <= 0.0:
        raise ValueError("maximum_absolute_position must be positive")
    if minimum < -maximum or minimum > maximum:
        raise ValueError("minimum_position must lie within the absolute position limit")
    if frame.empty:
        raise ValueError("walk-forward diagnostics require a non-empty frame")
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("walk-forward diagnostics require a DatetimeIndex")
    if frame.index.tz is None:
        raise ValueError("walk-forward diagnostics require timezone-aware timestamps")
    if frame.index.has_duplicates or not frame.index.is_monotonic_increasing:
        raise ValueError("walk-forward diagnostics require unique increasing timestamps")

    position = _finite_series(frame, "position")
    turnover = _finite_series(frame, "turnover")
    net_returns = _finite_series(frame, "strategy_return")
    position_limit_breach = (position < minimum - _POSITION_LIMIT_TOLERANCE) | (
        position > maximum + _POSITION_LIMIT_TOLERANCE
    )
    if position_limit_breach.any():
        breach_row = int(np.flatnonzero(position_limit_breach.to_numpy(copy=False))[0])
        raise ValueError(
            "walk-forward position breaches configured position limits at row "
            f"{breach_row}: {position.iloc[breach_row]:.12g} not in [{minimum:.12g}, {maximum:.12g}]"
        )
    if (turnover < 0.0).any():
        raise ValueError("walk-forward turnover must be non-negative")
    if (net_returns <= -1.0).any():
        raise ValueError("walk-forward strategy returns must remain greater than -100%")

    expected_turnover = (position - position.shift(1, fill_value=0.0)).abs()
    if not np.allclose(
        turnover.to_numpy(copy=False),
        expected_turnover.to_numpy(copy=False),
        rtol=0.0,
        atol=_POSITION_ADJUSTMENT_THRESHOLD,
    ):
        raise ValueError("walk-forward turnover must equal absolute position changes")

    observations = len(frame)
    absolute_position = position.abs()
    adjustments = turnover > _POSITION_ADJUSTMENT_THRESHOLD
    material_adjustments = turnover > _MATERIAL_POSITION_ADJUSTMENT_THRESHOLD
    active = absolute_position > _ACTIVE_POSITION_THRESHOLD

    episode_durations: list[int] = []
    completed_episode_returns: list[float] = []
    completed_episodes = 0
    open_episodes = 0
    row = 0
    while row < observations:
        if not bool(active.iloc[row]):
            row += 1
            continue
        start = row
        while row + 1 < observations and bool(active.iloc[row + 1]):
            row += 1
        last_active = row
        episode_durations.append(last_active - start + 1)
        if last_active + 1 < observations:
            completed_episodes += 1
            exit_row = last_active + 1
            episode_returns = net_returns.iloc[start : exit_row + 1]
            completed_episode_returns.append(float((1.0 + episode_returns).prod() - 1.0))
        else:
            open_episodes += 1
        row += 1

    positive_episode_profit = sum(value for value in completed_episode_returns if value > 0.0)
    negative_episode_loss = -sum(value for value in completed_episode_returns if value < 0.0)
    if negative_episode_loss > 0.0:
        episode_profit_factor: float | str = positive_episode_profit / negative_episode_loss
    elif positive_episode_profit > 0.0:
        episode_profit_factor = "unbounded"
    else:
        episode_profit_factor = "undefined"

    episode_win_rate = (
        sum(value > 0.0 for value in completed_episode_returns) / completed_episodes
        if completed_episodes
        else 0.0
    )
    average_holding_bars = float(np.mean(episode_durations)) if episode_durations else 0.0
    median_holding_bars = float(np.median(episode_durations)) if episode_durations else 0.0
    maximum_holding_bars = max(episode_durations, default=0)

    return_values = net_returns.to_numpy(copy=False)
    equity = np.cumprod(1.0 + return_values)
    running_peak = np.maximum.accumulate(np.concatenate(([1.0], equity)))[1:]
    drawdown = equity / running_peak - 1.0
    current_underwater_bars, longest_underwater_bars = _underwater_durations(drawdown)

    tail_observations = max(1, math.ceil(observations * _EXPECTED_SHORTFALL_TAIL_FRACTION))
    expected_shortfall = float(np.sort(return_values)[:tail_observations].mean())
    active_returns = net_returns[net_returns != 0.0]
    bar_hit_rate = float((active_returns > 0.0).mean()) if len(active_returns) else 0.0

    return {
        "diagnostic_schema": "walk_forward_path_v1",
        "observations": observations,
        "evaluation_start": frame.index[0].isoformat(),
        "evaluation_end": frame.index[-1].isoformat(),
        "declared_minimum_position": minimum,
        "declared_maximum_absolute_position": maximum,
        "position_limit_tolerance": _POSITION_LIMIT_TOLERANCE,
        "position_limit_passes": True,
        "position_adjustment_threshold": _POSITION_ADJUSTMENT_THRESHOLD,
        "material_position_adjustment_threshold": _MATERIAL_POSITION_ADJUSTMENT_THRESHOLD,
        "active_position_threshold": _ACTIVE_POSITION_THRESHOLD,
        "total_absolute_turnover": float(turnover.sum()),
        "annualized_instrument_turnover": float(turnover.mean() * ann),
        "position_adjustment_count": int(adjustments.sum()),
        "annualized_position_adjustment_count": float(adjustments.sum() * ann / observations),
        "material_position_adjustment_count": int(material_adjustments.sum()),
        "annualized_material_position_adjustment_count": float(
            material_adjustments.sum() * ann / observations
        ),
        "holding_episode_count": len(episode_durations),
        "completed_holding_episode_count": completed_episodes,
        "open_holding_episode_count": open_episodes,
        "holding_duration_basis": (
            "abs(position) > active_position_threshold; open episodes are truncated at "
            "evaluation_end; completed episode PnL includes the first inactive bar so the "
            "transition fee is included"
        ),
        "average_holding_duration_bars": average_holding_bars,
        "median_holding_duration_bars": median_holding_bars,
        "maximum_holding_duration_bars": maximum_holding_bars,
        "bar_hit_rate": bar_hit_rate,
        "completed_holding_episode_win_rate": float(episode_win_rate),
        "completed_holding_episode_profit_factor": episode_profit_factor,
        "average_absolute_exposure": float(absolute_position.mean()),
        "current_absolute_exposure": float(absolute_position.iloc[-1]),
        "maximum_absolute_exposure": float(absolute_position.max()),
        "worst_observation_return": float(return_values.min()),
        "expected_shortfall_95": expected_shortfall,
        "expected_shortfall_tail_observations": tail_observations,
        "current_drawdown": float(drawdown[-1]),
        "recomputed_maximum_drawdown": float(drawdown.min()),
        "current_underwater_duration_bars": current_underwater_bars,
        "longest_underwater_duration_bars": longest_underwater_bars,
    }
