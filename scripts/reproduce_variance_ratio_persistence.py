#!/usr/bin/env python3
"""Reproduce issue #720 on immutable public OKX 1H candle artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE = 0.0005
ANN = 8760.0
N = 43_441
TRAIN = (2_880, 17_520)
OOS = (17_520, 43_440)
FULL = (2_880, 43_440)
FOLD = 2_160
SEED = 20_260_731
EXPECTED = {
    "BTC-USDT": (
        "f967995a6acd5c4acd0a17dd030f02cd55441b3f83716e5a4118a58af71ca96e",
        "4efd9875f8205f2c44c6e26042b24bdfb89f077f7c89b2888a6bac9b645747e0",
    ),
    "ETH-USDT": (
        "ff53337ffbeafd237703ef6ff5f61a2e0b15df1fbd5954c17a8557e80324e907",
        "3c6ce0c424280f1e0b6210501380336190d832359895df9534e5c5a16d9ec6ed",
    ),
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path, market: str) -> pd.DataFrame:
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    full_hash, prefix_hash = EXPECTED[market]
    if digest(raw) != full_hash or digest(b"".join(lines[: N + 1])) != prefix_hash:
        raise ValueError(f"immutable hash mismatch: {market}")
    frame = pd.read_csv(path).iloc[:N].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if len(frame) != N or not (frame["confirm"].to_numpy() == 1).all():
        raise ValueError(f"invalid confirmed prefix: {market}")
    if not (frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all():
        raise ValueError(f"non-contiguous 1H chronology: {market}")
    return frame


def positions(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    close = frame["close"].to_numpy(float)
    hourly = np.r_[np.nan, np.log(close[1:] / close[:-1])]
    candidate = np.zeros(len(frame) - 1)
    benchmark = np.zeros(len(frame) - 1)
    state = 0.0
    prior_base = False
    for t in range(2_160, len(frame) - 1):
        if frame["timestamp"].iloc[t].hour != 0:
            continue
        base = close[t] > close[t - 2_160]
        benchmark[t + 1 :] = float(base)
        if not base:
            state = 0.0
        elif not prior_base:
            state = 1.0
        else:
            window = hourly[t - 719 : t + 1]
            variance = float(np.var(window))
            ratio = math.nan
            if variance > 0 and np.isfinite(window).all():
                sums = np.convolve(window, np.ones(24), mode="valid")
                ratio = float(np.var(sums) / (24.0 * variance))
            ret168 = math.log(close[t] / close[t - 168])
            if math.isfinite(ratio) and ratio < 1.0 and ret168 < 0:
                state = 0.5
            elif math.isfinite(ratio) and ratio > 1.0 and ret168 > 0:
                state = 1.0
        candidate[t + 1 :] = state
        prior_base = base
    if not np.isin(candidate, [0.0, 0.5, 1.0]).all():
        raise AssertionError("position domain failed")
    return candidate, benchmark


def returns(frame: pd.DataFrame, position: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    open_ = frame["open"].to_numpy(float)
    gross = open_[1:] / open_[:-1] - 1.0
    turnover = np.abs(np.diff(np.r_[0.0, position]))
    return position * gross - FEE * turnover, turnover


def sharpe(values: np.ndarray) -> float:
    std = float(np.std(values, ddof=1))
    return float(np.mean(values) / std * math.sqrt(ANN)) if std > 0 else math.nan


def compounded(values: np.ndarray) -> float:
    return float(np.prod(1.0 + values) - 1.0)


def drawdown(values: np.ndarray) -> float:
    equity = np.cumprod(1.0 + values)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])[1:]
    return float(np.min(equity / peaks - 1.0))


def metrics(net: np.ndarray, turnover: np.ndarray, span: tuple[int, int]) -> dict:
    start, end = span
    values = net[start:end]
    turns = float(np.sum(turnover[start:end]))
    return {
        "net_return": compounded(values),
        "sharpe": sharpe(values),
        "max_drawdown": drawdown(values),
        "turnover": turns,
        "fees": FEE * turns,
        "edge_per_turnover_bps": float(np.sum(values) / turns * 10_000),
    }


def basic_interval(point: float, draws: np.ndarray) -> list[float]:
    low, high = np.quantile(draws, [0.025, 0.975])
    return [float(2 * point - high), float(2 * point - low)]


def uncertainty(candidate: np.ndarray, benchmark: np.ndarray) -> dict:
    c = candidate[OOS[0] : OOS[1]]
    b = benchmark[OOS[0] : OOS[1]]
    n = len(c)
    blocks = math.ceil(n / 168)
    rng = np.random.default_rng(SEED)
    mean_draws = np.empty(5_000)
    sharpe_draws = np.empty(5_000)
    offsets = np.arange(168)
    for start in range(0, 5_000, 100):
        size = min(100, 5_000 - start)
        heads = rng.integers(0, n - 168 + 1, size=(size, blocks))
        indices = (heads[:, :, None] + offsets).reshape(size, -1)[:, :n]
        cs, bs = c[indices], b[indices]
        mean_draws[start : start + size] = np.mean(cs - bs, axis=1) * ANN
        cm, bm = np.mean(cs, axis=1), np.mean(bs, axis=1)
        cstd, bstd = np.std(cs, axis=1, ddof=1), np.std(bs, axis=1, ddof=1)
        sharpe_draws[start : start + size] = (cm / cstd - bm / bstd) * math.sqrt(ANN)
    mean_point = float(np.mean(c - b) * ANN)
    sharpe_point = sharpe(c) - sharpe(b)
    return {
        "mean_delta_annualized": {
            "point": mean_point,
            "ci95": basic_interval(mean_point, mean_draws),
        },
        "sharpe_delta": {
            "point": sharpe_point,
            "ci95": basic_interval(sharpe_point, sharpe_draws),
        },
    }


def breadth(frame: pd.DataFrame, candidate: np.ndarray, benchmark: np.ndarray) -> dict:
    folds = []
    positives = []
    for number in range(12):
        start = OOS[0] + number * FOLD
        end = start + FOLD
        c, b = compounded(candidate[start:end]), compounded(benchmark[start:end])
        folds.append({"fold": number + 1, "candidate": c, "benchmark_b1": b})
        if c > 0:
            positives.append(c)
    years = []
    timestamps = frame["timestamp"].iloc[1:].reset_index(drop=True)
    for year in sorted(set(timestamps.iloc[OOS[0] : OOS[1]].dt.year)):
        mask = np.flatnonzero(timestamps.iloc[OOS[0] : OOS[1]].dt.year.to_numpy() == year) + OOS[0]
        years.append(
            {
                "year": int(year),
                "candidate": compounded(candidate[mask]),
                "benchmark_b1": compounded(benchmark[mask]),
            }
        )
    residual = candidate[OOS[0] : OOS[1]] - benchmark[OOS[0] : OOS[1]]
    return {
        "profitable_folds": sum(row["candidate"] > 0 for row in folds),
        "profitable_years": sum(row["candidate"] > 0 for row in years),
        "improved_folds": sum(row["candidate"] > row["benchmark_b1"] for row in folds),
        "improved_years": sum(row["candidate"] > row["benchmark_b1"] for row in years),
        "positive_fold_concentration": max(positives) / sum(positives),
        "residual_sharpe": sharpe(residual),
        "folds": folds,
        "years": years,
    }


def market(path: Path, name: str) -> dict:
    frame = load(path, name)
    candidate_position, benchmark_position = positions(frame)
    candidate, candidate_turnover = returns(frame, candidate_position)
    benchmark, benchmark_turnover = returns(frame, benchmark_position)
    return {
        "training": {
            "candidate": metrics(candidate, candidate_turnover, TRAIN),
            "benchmark_b1": metrics(benchmark, benchmark_turnover, TRAIN),
        },
        "development_oos": {
            "candidate": metrics(candidate, candidate_turnover, OOS),
            "benchmark_b1": metrics(benchmark, benchmark_turnover, OOS),
        },
        "full_scored": {
            "candidate": metrics(candidate, candidate_turnover, FULL),
            "benchmark_b1": metrics(benchmark, benchmark_turnover, FULL),
        },
        "breadth": breadth(frame, candidate, benchmark),
        "uncertainty": uncertainty(candidate, benchmark),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {
        "family_id": "variance-ratio-persistence-risk-state-1h-v1",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "markets": {
            "BTC-USDT": market(args.btc_csv, "BTC-USDT"),
            "ETH-USDT": market(args.eth_csv, "ETH-USDT"),
        },
        "verdict": "reject_exact_variance_ratio_persistence_risk_state_family",
    }
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
