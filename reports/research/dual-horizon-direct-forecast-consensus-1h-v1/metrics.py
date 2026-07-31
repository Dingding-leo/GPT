"""Performance, breadth, and paired dependence-aware uncertainty metrics."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd
from common import ANNUAL_HOURS, BLOCK_HOURS, FOLD_HOURS, OOS, finite_or_none


def metrics(path: dict[str, np.ndarray], start: int, end: int) -> dict[str, Any]:
    net = path["net"][start:end]
    gross = path["gross"][start:end]
    fee = path["fee"][start:end]
    changes = path["changes"][start:end]
    position = path["position"][start:end]
    wealth = np.cumprod(1.0 + net)
    curve = np.r_[1.0, wealth]
    drawdown = curve / np.maximum.accumulate(curve) - 1.0
    sd = float(np.std(net, ddof=1))
    sharpe = float(np.mean(net) / sd * math.sqrt(ANNUAL_HOURS)) if sd > 0 else math.nan
    turnover = float(np.sum(changes))
    return {
        "net_return": float(wealth[-1] - 1.0),
        "gross_arithmetic_return": float(np.sum(gross)),
        "net_arithmetic_return": float(np.sum(net)),
        "annualized_mean_return": float(np.mean(net) * ANNUAL_HOURS),
        "sharpe": finite_or_none(sharpe),
        "max_drawdown": float(np.min(drawdown)),
        "turnover": turnover,
        "annualized_turnover": float(turnover / len(net) * ANNUAL_HOURS),
        "fees": float(np.sum(fee)),
        "edge_per_turn_bps": (
            finite_or_none(float(np.sum(net) / turnover * 10_000))
            if turnover > 0
            else None
        ),
        "exposure": float(np.mean(position)),
        "position_changes": int(np.count_nonzero(changes)),
    }


def sharpe_value(values: np.ndarray) -> float:
    sd = float(np.std(values, ddof=1))
    return float(np.mean(values) / sd * math.sqrt(ANNUAL_HOURS)) if sd > 0 else math.nan


def residual_sharpe(candidate: np.ndarray, benchmark: np.ndarray) -> float | None:
    return finite_or_none(sharpe_value(candidate - benchmark))


def fold_year_diagnostics(
    path: dict[str, np.ndarray], timestamps: pd.Series
) -> dict[str, Any]:
    start, end = OOS
    fold_returns = [
        float(np.prod(1.0 + path["net"][left : left + FOLD_HOURS]) - 1.0)
        for left in range(start, end, FOLD_HOURS)
    ]
    positive = [value for value in fold_returns if value > 0]
    concentration = max(positive) / sum(positive) if positive else math.inf
    interval_year = timestamps.iloc[:-1].dt.year.to_numpy()
    year_returns: dict[str, float] = {}
    for year in sorted(set(interval_year[start:end])):
        mask = interval_year[start:end] == year
        values = path["net"][start:end][mask]
        year_returns[str(int(year))] = float(np.prod(1.0 + values) - 1.0)
    return {
        "fold_returns": fold_returns,
        "profitable_folds": int(sum(value > 0 for value in fold_returns)),
        "positive_fold_concentration": finite_or_none(float(concentration)),
        "year_returns": year_returns,
        "profitable_years": int(sum(value > 0 for value in year_returns.values())),
    }


def bootstrap_starts(n: int, resamples: int, seed: int) -> np.ndarray:
    if n < BLOCK_HOURS:
        raise ValueError("sample shorter than bootstrap block")
    blocks = math.ceil(n / BLOCK_HOURS)
    rng = np.random.default_rng(seed)
    return rng.integers(0, n - BLOCK_HOURS + 1, size=(resamples, blocks))


def sampled_indices(starts: np.ndarray, n: int) -> np.ndarray:
    base = np.arange(BLOCK_HOURS)
    return np.concatenate([start + base for start in starts])[:n]


def paired_bootstrap(
    candidate: np.ndarray,
    benchmark: np.ndarray,
    starts: np.ndarray,
) -> dict[str, Any]:
    if len(candidate) != len(benchmark):
        raise ValueError("bootstrap length mismatch")
    mean_delta = np.empty(len(starts))
    sharpe_delta = np.empty(len(starts))
    for k, block_starts in enumerate(starts):
        idx = sampled_indices(block_starts, len(candidate))
        c = candidate[idx]
        b = benchmark[idx]
        mean_delta[k] = float(np.mean(c - b) * ANNUAL_HOURS)
        sharpe_delta[k] = sharpe_value(c) - sharpe_value(b)
    return {
        "method": "paired_non_circular_moving_block",
        "block_hours": BLOCK_HOURS,
        "resamples": int(len(starts)),
        "annualized_mean_delta_point": float(
            np.mean(candidate - benchmark) * ANNUAL_HOURS
        ),
        "annualized_mean_delta_ci95": [
            float(value) for value in np.quantile(mean_delta, [0.025, 0.975])
        ],
        "sharpe_delta_point": finite_or_none(
            sharpe_value(candidate) - sharpe_value(benchmark)
        ),
        "sharpe_delta_ci95": [
            float(value) for value in np.nanquantile(sharpe_delta, [0.025, 0.975])
        ],
    }
