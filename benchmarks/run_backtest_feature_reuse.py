#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gc
import hashlib
import itertools
import statistics
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path

import numpy as np
import pandas as pd

from gpt_quant import StrategyConfig, load_price_csv, run_backtest, validate_prices
from gpt_quant.backtest import BacktestResult

Workload = Callable[[], object]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark validated-price and volatility-window reuse on real market data."
    )
    parser.add_argument("--csv", required=True, help="Timestamp/close real-market CSV.")
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--timestamp-col", default="timestamp")
    parser.add_argument("--close-col", default="close")
    parser.add_argument("--repetitions", type=int, default=21)
    return parser.parse_args()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_grid() -> list[StrategyConfig]:
    return [
        StrategyConfig(
            momentum_lookback=momentum,
            reversal_lookback=reversal,
            trend_weight=trend_weight,
            reversal_weight=round(1.0 - trend_weight, 10),
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=365,
        )
        for momentum, reversal, trend_weight in itertools.product(
            (30, 90, 180),
            (2, 5, 10),
            (0.55, 0.70, 0.85),
        )
    ]


def _baseline_build_target_position(prices: pd.Series, config: StrategyConfig) -> pd.Series:
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
        lower=0.0,
        upper=config.max_abs_position,
    )
    target = (directional_signal * volatility_scalar).clip(
        config.min_position,
        config.max_abs_position,
    )
    return target.replace([np.inf, -np.inf], np.nan).fillna(0.0).rename("target_position")


def _baseline_run_backtest(prices: pd.Series, config: StrategyConfig) -> BacktestResult:
    clean = validate_prices(prices)
    target_position = _baseline_build_target_position(clean, config)
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
    return BacktestResult(frame=frame, config=config)


def _elapsed_seconds(workload: Workload) -> float:
    started = time.perf_counter()
    workload()
    return time.perf_counter() - started


def _paired_medians(
    baseline: Workload,
    optimized: Workload,
    repetitions: int,
) -> tuple[float, float]:
    baseline_samples: list[float] = []
    optimized_samples: list[float] = []
    for repetition in range(repetitions):
        if repetition % 2 == 0:
            baseline_samples.append(_elapsed_seconds(baseline))
            optimized_samples.append(_elapsed_seconds(optimized))
        else:
            optimized_samples.append(_elapsed_seconds(optimized))
            baseline_samples.append(_elapsed_seconds(baseline))
    return statistics.median(baseline_samples), statistics.median(optimized_samples)


def _peak_allocation_bytes(workload: Workload) -> int:
    gc.collect()
    tracemalloc.start()
    workload()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak


def main() -> int:
    args = parse_args()
    if args.repetitions < 3:
        raise ValueError("repetitions must be at least 3")
    actual_sha256 = file_sha256(args.csv)
    if actual_sha256 != args.expected_sha256.lower():
        raise ValueError("CSV SHA-256 does not match --expected-sha256")

    prices = load_price_csv(
        args.csv,
        timestamp_col=args.timestamp_col,
        close_col=args.close_col,
    )
    candidates = candidate_grid()
    baseline_results = [_baseline_run_backtest(prices, config) for config in candidates]
    optimized_results = [run_backtest(prices, config) for config in candidates]
    for baseline_result, optimized_result in zip(
        baseline_results,
        optimized_results,
        strict=True,
    ):
        pd.testing.assert_frame_equal(
            baseline_result.frame,
            optimized_result.frame,
            check_exact=True,
        )

    def baseline_workload() -> list[BacktestResult]:
        return [_baseline_run_backtest(prices, config) for config in candidates]

    def optimized_workload() -> list[BacktestResult]:
        return [run_backtest(prices, config) for config in candidates]

    for _ in range(3):
        baseline_workload()
        optimized_workload()
    baseline, optimized = _paired_medians(
        baseline_workload,
        optimized_workload,
        args.repetitions,
    )
    baseline_peak = _peak_allocation_bytes(baseline_workload)
    optimized_peak = _peak_allocation_bytes(optimized_workload)

    print(f"csv_sha256={actual_sha256}")
    print(f"observations={len(prices)}")
    print(f"candidates={len(candidates)}")
    print(f"repetitions={args.repetitions}")
    print("fee_bps=5.0")
    print("timing_order=alternating_paired")
    print("frame_equivalence=exact")
    print(f"baseline_median_seconds={baseline:.9f}")
    print(f"optimized_median_seconds={optimized:.9f}")
    print(f"reduction_percent={(1.0 - optimized / baseline) * 100.0:.2f}")
    print(f"speedup={baseline / optimized:.3f}x")
    print(f"baseline_peak_python_bytes={baseline_peak}")
    print(f"optimized_peak_python_bytes={optimized_peak}")
    print(f"peak_reduction_percent={(1.0 - optimized_peak / baseline_peak) * 100.0:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
