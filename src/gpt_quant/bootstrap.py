from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .metrics import performance_metrics

_METRICS = ("cagr", "sharpe", "calmar", "max_drawdown")


@dataclass(frozen=True, slots=True)
class BootstrapComparisonResult:
    settings: dict[str, Any]
    point_estimates: dict[str, dict[str, float]]
    comparisons: dict[str, dict[str, dict[str, float | bool]]]
    hypothesis: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "settings": self.settings,
            "point_estimates": self.point_estimates,
            "comparisons": self.comparisons,
            "hypothesis": self.hypothesis,
        }


def validate_chronological_returns_frame(
    frame: pd.DataFrame,
    *,
    timestamp_column: str = "timestamp",
    expected_frequency: str | pd.Timedelta | None = None,
) -> pd.DataFrame:
    """Parse UTC timestamps and fail closed when row order cannot represent market time."""

    if timestamp_column not in frame:
        raise ValueError(f"missing timestamp column: {timestamp_column}")
    timestamps = pd.to_datetime(frame[timestamp_column], errors="coerce", utc=True)
    if timestamps.isna().any():
        raise ValueError(
            "timestamp column must contain only valid UTC-compatible timestamps"
        )
    if timestamps.duplicated().any():
        raise ValueError("timestamp column must not contain duplicates")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("timestamp column must be strictly increasing")

    if expected_frequency is not None and len(timestamps) > 1:
        interval = pd.Timedelta(expected_frequency)
        if interval <= pd.Timedelta(0):
            raise ValueError("expected_frequency must be positive")
        deltas = timestamps.diff().iloc[1:]
        if not deltas.eq(interval).all():
            raise ValueError(f"timestamp cadence must be exactly {interval}")

    validated = frame.copy()
    validated[timestamp_column] = timestamps
    return validated


def _metric_values(returns: np.ndarray, annualization: int) -> dict[str, float]:
    frame = pd.DataFrame({"strategy_return": returns})
    metrics = performance_metrics(frame, annualization=annualization)
    return {name: float(metrics[name]) for name in _METRICS}


def moving_block_indices(
    observations: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if observations < 2:
        raise ValueError("observations must be at least 2")
    if not 1 <= block_length <= observations:
        raise ValueError("block_length must be between 1 and observations")
    blocks_needed = math.ceil(observations / block_length)
    latest_start = observations - block_length
    starts = rng.integers(0, latest_start + 1, size=blocks_needed)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observations]


def paired_moving_block_bootstrap(
    frame: pd.DataFrame,
    *,
    strategy_column: str,
    benchmark_columns: Mapping[str, str],
    block_length: int = 20,
    resamples: int = 2_000,
    confidence: float = 0.95,
    annualization: int = 365,
    seed: int = 0,
    hypothesis_metrics: Sequence[str] = ("calmar", "max_drawdown"),
) -> BootstrapComparisonResult:
    if resamples < 100:
        raise ValueError("resamples must be at least 100")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if annualization <= 0:
        raise ValueError("annualization must be positive")
    if not benchmark_columns:
        raise ValueError("benchmark_columns cannot be empty")
    unknown_metrics = set(hypothesis_metrics) - set(_METRICS)
    if unknown_metrics:
        raise ValueError(f"unknown hypothesis metrics: {sorted(unknown_metrics)}")

    series_columns = {"strategy": strategy_column, **dict(benchmark_columns)}
    missing = [column for column in series_columns.values() if column not in frame]
    if missing:
        raise ValueError(f"missing return columns: {sorted(set(missing))}")

    numeric = frame[list(series_columns.values())].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("return columns must contain only finite numeric values")
    values = numeric.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("return columns must contain only finite numeric values")
    if np.any(values <= -1.0):
        raise ValueError("returns must be greater than -1")

    observations = len(values)
    if observations < max(20, block_length * 2):
        raise ValueError("not enough observations for the requested block length")

    names = list(series_columns)
    point_estimates = {
        name: _metric_values(values[:, index], annualization)
        for index, name in enumerate(names)
    }
    distributions = {
        benchmark: {metric: np.empty(resamples, dtype=float) for metric in _METRICS}
        for benchmark in benchmark_columns
    }

    rng = np.random.default_rng(seed)
    for sample_number in range(resamples):
        indices = moving_block_indices(observations, block_length, rng)
        sampled_metrics = [
            _metric_values(values[indices, index], annualization)
            for index in range(len(names))
        ]
        strategy_metrics = sampled_metrics[0]
        for benchmark_index, benchmark in enumerate(benchmark_columns, start=1):
            benchmark_metrics = sampled_metrics[benchmark_index]
            for metric in _METRICS:
                distributions[benchmark][metric][sample_number] = (
                    strategy_metrics[metric] - benchmark_metrics[metric]
                )

    alpha = 1.0 - confidence
    comparisons: dict[str, dict[str, dict[str, float | bool]]] = {}
    for benchmark, metric_distributions in distributions.items():
        comparisons[benchmark] = {}
        for metric, distribution in metric_distributions.items():
            lower, median, upper = np.quantile(
                distribution,
                [alpha / 2.0, 0.5, 1.0 - alpha / 2.0],
            )
            observed_delta = (
                point_estimates["strategy"][metric] - point_estimates[benchmark][metric]
            )
            comparisons[benchmark][metric] = {
                "observed_delta": float(observed_delta),
                "ci_lower": float(lower),
                "ci_median": float(median),
                "ci_upper": float(upper),
                "probability_positive": float(np.mean(distribution > 0.0)),
                "lower_bound_positive": bool(lower > 0.0),
            }

    metric_support = {
        metric: all(
            bool(comparisons[benchmark][metric]["lower_bound_positive"])
            for benchmark in benchmark_columns
        )
        for metric in hypothesis_metrics
    }
    supported_metrics = [
        metric for metric, supported in metric_support.items() if supported
    ]
    if all(metric_support.values()):
        verdict = "supported"
    elif supported_metrics:
        verdict = "partially supported"
    else:
        verdict = "rejected"

    return BootstrapComparisonResult(
        settings={
            "observations": observations,
            "block_length": block_length,
            "resamples": resamples,
            "confidence": confidence,
            "annualization": annualization,
            "seed": seed,
            "strategy_column": strategy_column,
            "benchmark_columns": dict(benchmark_columns),
            "paired_resampling": True,
            "serial_dependence_method": "moving block bootstrap without circular wrapping",
        },
        point_estimates=point_estimates,
        comparisons=comparisons,
        hypothesis={
            "metrics": list(hypothesis_metrics),
            "metric_support": metric_support,
            "verdict": verdict,
            "supported_metrics": supported_metrics,
        },
    )
