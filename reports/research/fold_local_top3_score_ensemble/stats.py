from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from .core import (
    ANNUALIZATION,
    BASELINE_COST_BPS,
    BLOCK_LENGTH,
    CONFIDENCE,
    RESAMPLES,
    SELECTION_BARS,
    TEST_BARS,
    _rebased_window,
    candidate_frame,
    candidate_grid,
)


def return_metrics(returns: pd.Series | np.ndarray) -> dict[str, float | int]:
    values = np.asarray(returns, dtype=float)
    if values.size == 0 or not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("returns must be finite, non-empty, and greater than -1")
    observations = int(values.size)
    growth = float(np.prod(1.0 + values))
    total_return = growth - 1.0
    cagr = growth ** (ANNUALIZATION / observations) - 1.0 if growth > 0.0 else -1.0
    mean = float(values.mean())
    standard_deviation = float(values.std(ddof=0))
    annualized_mean = mean * ANNUALIZATION
    annualized_volatility = standard_deviation * math.sqrt(ANNUALIZATION)
    sharpe = mean / standard_deviation * math.sqrt(ANNUALIZATION) if standard_deviation > 0 else 0.0
    downside = np.minimum(values, 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))))
    sortino = (
        mean / downside_deviation * math.sqrt(ANNUALIZATION) if downside_deviation > 0 else 0.0
    )
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    max_drawdown = float(drawdown.min())
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0.0 else 0.0
    return {
        "observations": observations,
        "total_return": total_return,
        "cagr": cagr,
        "annualized_arithmetic_mean": annualized_mean,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
    }


def frame_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    values = return_metrics(frame["strategy_return"])
    values.update(
        {
            "annualized_turnover": float(frame["turnover"].mean()) * ANNUALIZATION,
            "average_abs_exposure": float(frame["position"].abs().mean()),
            "exchange_fee_sum": float(frame["trading_cost"].sum()),
        }
    )
    return values


def selection_score(metrics: dict[str, float | int]) -> float:
    return (
        float(metrics["sharpe"])
        + 0.20 * float(metrics["calmar"])
        - 0.50 * abs(float(metrics["max_drawdown"]))
        - 0.01 * float(metrics["annualized_turnover"])
    )


def build_top_k_path(
    prices: pd.Series,
    *,
    top_k: int,
    cost_bps: float = BASELINE_COST_BPS,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    grid = candidate_grid()
    if top_k <= 0 or top_k > len(grid):
        raise ValueError("top_k must be within the candidate grid")
    cached = {candidate: candidate_frame(prices, candidate) for candidate in grid}
    previous_position = 0.0
    frames: list[pd.DataFrame] = []
    fold_records: list[dict[str, Any]] = []
    for fold, test_start_index in enumerate(
        range(SELECTION_BARS, len(prices), TEST_BARS),
        start=1,
    ):
        test_end_index = min(test_start_index + TEST_BARS, len(prices)) - 1
        if test_end_index - test_start_index + 1 < max(20, TEST_BARS // 2):
            break
        selection_end_index = test_start_index - 1
        selection_start_index = selection_end_index - SELECTION_BARS + 1
        selection_start = prices.index[selection_start_index]
        selection_end = prices.index[selection_end_index]
        test_start = prices.index[test_start_index]
        test_end = prices.index[test_end_index]
        ranked: list[tuple[float, tuple[int, int, float], dict[str, float | int]]] = []
        for candidate in grid:
            window = _rebased_window(
                cached[candidate].loc[selection_start:selection_end],
                0.0,
                BASELINE_COST_BPS,
            )
            metrics = frame_metrics(window)
            score = selection_score(metrics)
            if np.isfinite(score):
                ranked.append((score, candidate, metrics))
        if len(ranked) != len(grid):
            raise RuntimeError("every declared candidate must produce a finite selection score")
        ranked.sort(key=lambda item: item[0], reverse=True)
        selected = ranked[:top_k]
        positions = pd.concat(
            [
                cached[candidate].loc[test_start:test_end, "position"]
                for _, candidate, _ in selected
            ],
            axis=1,
        ).mean(axis=1)
        targets = pd.concat(
            [
                cached[candidate].loc[test_start:test_end, "target_position"]
                for _, candidate, _ in selected
            ],
            axis=1,
        ).mean(axis=1)
        asset_return = prices.pct_change().fillna(0.0).loc[test_start:test_end]
        turnover = positions.diff().abs()
        turnover.iloc[0] = abs(float(positions.iloc[0]) - previous_position)
        gross = positions * asset_return
        trading_cost = turnover * cost_bps / 10_000.0
        frame = pd.DataFrame(
            {
                "asset_return": asset_return,
                "target_position": targets,
                "position": positions,
                "turnover": turnover,
                "gross_strategy_return": gross,
                "trading_cost": trading_cost,
                "strategy_return": gross - trading_cost,
                "fold": fold,
            },
            index=positions.index,
        )
        frames.append(frame)
        previous_position = float(positions.iloc[-1])
        fold_records.append(
            {
                "fold": fold,
                "selection_start": selection_start.isoformat(),
                "selection_end": selection_end.isoformat(),
                "test_start": test_start.isoformat(),
                "test_end": test_end.isoformat(),
                "candidates_tested": len(ranked),
                "selected": [
                    {
                        "rank": rank,
                        "score": float(score),
                        "momentum_lookback": int(candidate[0]),
                        "reversal_lookback": int(candidate[1]),
                        "trend_weight": float(candidate[2]),
                    }
                    for rank, (score, candidate, _) in enumerate(selected, start=1)
                ],
                "test_metrics": frame_metrics(frame),
            }
        )
    combined = pd.concat(frames).sort_index()
    if combined.index.has_duplicates:
        raise RuntimeError("test folds must not overlap")
    return combined, fold_records


def reprice(frame: pd.DataFrame, cost_bps: float) -> pd.DataFrame:
    result = frame.copy()
    result["trading_cost"] = result["turnover"] * cost_bps / 10_000.0
    result["strategy_return"] = result["gross_strategy_return"] - result["trading_cost"]
    return result


def delay_path(frame: pd.DataFrame, total_delay_bars: int, cost_bps: float) -> pd.DataFrame:
    if total_delay_bars < 1:
        raise ValueError("total_delay_bars must be at least one")
    extra_delay = total_delay_bars - 1
    position = frame["position"].shift(extra_delay).fillna(0.0)
    turnover = position.diff().abs()
    turnover.iloc[0] = abs(float(position.iloc[0]))
    gross = position * frame["asset_return"]
    trading_cost = turnover * cost_bps / 10_000.0
    return pd.DataFrame(
        {
            "asset_return": frame["asset_return"],
            "position": position,
            "turnover": turnover,
            "gross_strategy_return": gross,
            "trading_cost": trading_cost,
            "strategy_return": gross - trading_cost,
            "fold": frame["fold"],
        },
        index=frame.index,
    )


def fold_stability(frame: pd.DataFrame) -> dict[str, Any]:
    records = [
        {"fold": int(fold), "return": float((1.0 + group["strategy_return"]).prod() - 1.0)}
        for fold, group in frame.groupby("fold", sort=True)
    ]
    positive = [record["return"] for record in records if record["return"] > 0.0]
    positive_total = sum(positive)
    concentration = max(positive) / positive_total if positive_total > 0.0 else 1.0
    minimum_profitable = math.ceil(len(records) / 2)
    passes = len(positive) >= minimum_profitable and concentration <= 0.50
    return {
        "fold_count": len(records),
        "profitable_folds": len(positive),
        "positive_fold_ratio": len(positive) / len(records),
        "best_fold_total_return": max(record["return"] for record in records),
        "worst_fold_total_return": min(record["return"] for record in records),
        "max_positive_fold_share": concentration,
        "minimum_profitable_folds": minimum_profitable,
        "maximum_allowed_positive_fold_share": 0.50,
        "passes": passes,
        "failure_reasons": []
        if passes
        else [
            reason
            for condition, reason in (
                (
                    len(positive) < minimum_profitable,
                    "fewer than half of OOS folds are profitable",
                ),
                (
                    concentration > 0.50,
                    "one fold contributes more than half of positive fold return",
                ),
            )
            if condition
        ],
    }


def calendar_stability(frame: pd.DataFrame) -> dict[str, Any]:
    returns = frame["strategy_return"]
    years: list[dict[str, Any]] = []
    for year, group in returns.groupby(returns.index.year, sort=True):
        years.append(
            {
                "year": int(year),
                "return": float((1.0 + group).prod() - 1.0),
                "partial": not (
                    group.index[0].month == 1
                    and group.index[0].day == 1
                    and group.index[-1].month == 12
                    and group.index[-1].day == 31
                ),
            }
        )
    complete = [record for record in years if not record["partial"]]
    profitable = sum(record["return"] > 0.0 for record in complete)
    ratio = profitable / len(complete) if complete else 0.0
    passes = (
        len(complete) >= 4
        and ratio >= 0.60
        and min((record["return"] for record in complete), default=-math.inf) > -0.20
    )
    return {
        "years": years,
        "completed_year_count": len(complete),
        "profitable_completed_years": profitable,
        "profitable_completed_year_ratio": ratio,
        "passes": passes,
    }


def expected_shortfall_5pct(returns: pd.Series | np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    count = math.ceil(0.05 * len(values))
    return float(np.sort(values)[:count].mean())


def noncircular_block_indices(
    observations: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    blocks_needed = math.ceil(observations / block_length)
    starts = rng.integers(0, observations - block_length + 1, size=blocks_needed)
    return np.concatenate([np.arange(start, start + block_length) for start in starts])[
        :observations
    ]


def paired_metric_delta_bootstrap(
    candidate: pd.Series,
    comparator: pd.Series,
    *,
    seed: int,
) -> dict[str, Any]:
    candidate_values = candidate.to_numpy(dtype=float)
    comparator_values = comparator.to_numpy(dtype=float)
    if candidate_values.shape != comparator_values.shape:
        raise ValueError("paired returns must have identical shapes")
    rng = np.random.default_rng(seed)
    sharpe_deltas = np.empty(RESAMPLES)
    calmar_deltas = np.empty(RESAMPLES)
    for resample in range(RESAMPLES):
        indices = noncircular_block_indices(len(candidate_values), BLOCK_LENGTH, rng)
        candidate_metrics = return_metrics(candidate_values[indices])
        comparator_metrics = return_metrics(comparator_values[indices])
        sharpe_deltas[resample] = float(candidate_metrics["sharpe"]) - float(
            comparator_metrics["sharpe"]
        )
        calmar_deltas[resample] = float(candidate_metrics["calmar"]) - float(
            comparator_metrics["calmar"]
        )
    alpha = (1.0 - CONFIDENCE) / 2.0
    return {
        "sharpe_delta": {
            "point": float(return_metrics(candidate)["sharpe"])
            - float(return_metrics(comparator)["sharpe"]),
            "lower": float(np.quantile(sharpe_deltas, alpha)),
            "upper": float(np.quantile(sharpe_deltas, 1.0 - alpha)),
            "probability_positive": float(np.mean(sharpe_deltas > 0.0)),
        },
        "calmar_delta": {
            "point": float(return_metrics(candidate)["calmar"])
            - float(return_metrics(comparator)["calmar"]),
            "lower": float(np.quantile(calmar_deltas, alpha)),
            "upper": float(np.quantile(calmar_deltas, 1.0 - alpha)),
            "probability_positive": float(np.mean(calmar_deltas > 0.0)),
        },
    }


def absolute_return_bootstrap(returns: pd.Series, *, seed: int) -> dict[str, float]:
    values = returns.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(RESAMPLES)
    sharpes = np.empty(RESAMPLES)
    for resample in range(RESAMPLES):
        indices = noncircular_block_indices(len(values), BLOCK_LENGTH, rng)
        metrics = return_metrics(values[indices])
        means[resample] = float(metrics["annualized_arithmetic_mean"])
        sharpes[resample] = float(metrics["sharpe"])
    alpha = (1.0 - CONFIDENCE) / 2.0
    return {
        "annualized_mean_lower": float(np.quantile(means, alpha)),
        "sharpe_lower": float(np.quantile(sharpes, alpha)),
    }
