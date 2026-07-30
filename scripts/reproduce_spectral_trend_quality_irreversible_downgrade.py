#!/usr/bin/env python3
"""Reproduce issue #725 with immutable public OKX 1H candles."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FEE = 0.0005
ANN = 8760.0
ROWS = 43_441
TRAIN = (2_880, 17_520)
OOS = (17_520, 43_440)
FULL = (2_880, 43_440)
FOLD = 2_160
BLOCK = 168
DRAWS = 5_000
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


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path, market: str, rows: int | None = ROWS) -> pd.DataFrame:
    raw = path.read_bytes()
    lines = raw.splitlines(keepends=True)
    full_hash, prefix_hash = EXPECTED[market]
    if sha(raw) != full_hash:
        raise ValueError(f"full hash mismatch: {market}")
    if sha(b"".join(lines[: ROWS + 1])) != prefix_hash:
        raise ValueError(f"prefix hash mismatch: {market}")
    frame = pd.read_csv(path, nrows=rows)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if not (frame["confirm"].to_numpy() == 1).all():
        raise ValueError(f"unconfirmed bars: {market}")
    step = frame["timestamp"].diff().dropna()
    if not (step == pd.Timedelta(hours=1)).all():
        raise ValueError(f"non-contiguous chronology: {market}")
    return frame


def ratio(window: np.ndarray) -> float:
    centered = window - window.mean()
    power = np.abs(np.fft.rfft(centered)) ** 2
    low = float(power[1:181].mean())
    high = float(power[181:361].mean())
    return low / high if high > 0 else math.inf


def positions(frame: pd.DataFrame) -> tuple[dict[str, np.ndarray], list[int]]:
    close = frame["close"].to_numpy(float)
    hours = frame["timestamp"].dt.hour.to_numpy()
    log_returns = np.diff(np.log(close))
    n = len(frame) - 1
    candidate = np.zeros(n)
    daily = np.zeros(n)
    hourly = np.zeros(n)
    prior = 0
    downgraded = False
    triggers: list[int] = []
    for t in range(2_160, len(frame) - 1):
        base = int(close[t] > close[t - 2_160])
        hourly[t + 1 :] = base
        if hours[t] != 0:
            continue
        daily[t + 1 :] = base
        onset = base == 1 and prior == 0
        if base == 0:
            target = 0.0
            downgraded = False
        elif onset:
            target = 1.0
            downgraded = False
        elif downgraded:
            target = 0.5
        elif ratio(log_returns[t - 720 : t]) < 1 and close[t] < close[t - 168]:
            target = 0.5
            downgraded = True
            triggers.append(t + 1)
        else:
            target = 1.0
        candidate[t + 1 :] = target
        prior = base
    if not np.isin(candidate, [0.0, 0.5, 1.0]).all():
        raise AssertionError("invalid candidate positions")
    return {"candidate": candidate, "b1": daily, "b0": hourly}, triggers


def returns(
    frame: pd.DataFrame,
    position: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    open_ = frame["open"].to_numpy(float)
    gross = open_[1:] / open_[:-1] - 1
    turnover = np.abs(np.diff(np.r_[0.0, position]))
    net = position * gross - FEE * turnover
    return net, turnover, gross


def compounded(values: np.ndarray) -> float:
    return float(np.prod(1 + values) - 1)


def sharpe(values: np.ndarray) -> float:
    std = float(values.std(ddof=1))
    return float(values.mean() / std * math.sqrt(ANN)) if std > 0 else math.nan


def metric(
    net: np.ndarray,
    turn: np.ndarray,
    span: tuple[int, int],
) -> dict[str, float]:
    start, end = span
    values = net[start:end]
    turnover = float(turn[start:end].sum())
    equity = np.cumprod(1 + values)
    peaks = np.maximum.accumulate(np.r_[1.0, equity])[1:]
    arithmetic = float(values.sum())
    return {
        "net_return": compounded(values),
        "sharpe": sharpe(values),
        "max_drawdown": float((equity / peaks - 1).min()),
        "turnover": turnover,
        "fees": FEE * turnover,
        "edge_per_turnover_bps": arithmetic / turnover * 10_000,
    }


def breadth(
    frame: pd.DataFrame,
    candidate: np.ndarray,
    b1: np.ndarray,
) -> dict[str, Any]:
    folds = []
    for number in range(12):
        start = OOS[0] + number * FOLD
        end = start + FOLD
        folds.append((compounded(candidate[start:end]), compounded(b1[start:end])))
    positive = [value for value, _ in folds if value > 0]
    timestamps = frame["timestamp"].iloc[1:].reset_index(drop=True)
    years = timestamps.iloc[OOS[0] : OOS[1]].dt.year.to_numpy()
    year_rows = []
    for year in sorted(set(years)):
        index = np.flatnonzero(years == year) + OOS[0]
        year_rows.append((compounded(candidate[index]), compounded(b1[index])))
    residual = candidate[OOS[0] : OOS[1]] - b1[OOS[0] : OOS[1]]
    return {
        "profitable_folds": sum(value > 0 for value, _ in folds),
        "profitable_years": sum(value > 0 for value, _ in year_rows),
        "improved_folds": sum(value > base for value, base in folds),
        "improved_years": sum(value > base for value, base in year_rows),
        "positive_fold_concentration": max(positive) / sum(positive),
        "residual_sharpe": sharpe(residual),
    }


def basic_interval(point: float, values: np.ndarray) -> list[float]:
    low, high = np.quantile(values, [0.025, 0.975])
    return [float(2 * point - high), float(2 * point - low)]


def uncertainty(candidate: np.ndarray, b1: np.ndarray) -> dict[str, Any]:
    c = candidate[OOS[0] : OOS[1]]
    b = b1[OOS[0] : OOS[1]]
    n = len(c)
    blocks = math.ceil(n / BLOCK)
    offsets = np.arange(BLOCK)
    rng = np.random.default_rng(SEED)
    mean_draws = np.empty(DRAWS)
    sharpe_draws = np.empty(DRAWS)
    for start in range(0, DRAWS, 100):
        size = min(100, DRAWS - start)
        heads = rng.integers(0, n - BLOCK + 1, (size, blocks))
        index = (heads[:, :, None] + offsets).reshape(size, -1)[:, :n]
        cs = c[index]
        bs = b[index]
        mean_draws[start : start + size] = (cs - bs).mean(axis=1) * ANN
        c_ratio = cs.mean(axis=1) / cs.std(axis=1, ddof=1)
        b_ratio = bs.mean(axis=1) / bs.std(axis=1, ddof=1)
        sharpe_draws[start : start + size] = (c_ratio - b_ratio) * math.sqrt(ANN)
    mean_point = float((c - b).mean() * ANN)
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


def diagnostics(
    triggers: list[int],
    position: dict[str, np.ndarray],
    net: dict[str, np.ndarray],
    turn: dict[str, np.ndarray],
    gross: np.ndarray,
    span: tuple[int, int],
) -> dict[str, Any]:
    start, end = span
    selected = [index for index in triggers if start <= index < end]
    mask = (position["candidate"][start:end] == 0.5) & (position["b1"][start:end] == 1)
    difference = position["candidate"][start:end] - position["b1"][start:end]
    timing = float((difference * gross[start:end]).sum())
    turn_difference = turn["candidate"][start:end] - turn["b1"][start:end]
    fee = float(-FEE * turn_difference.sum())
    delta = float((net["candidate"][start:end] - net["b1"][start:end]).sum())
    if abs(delta - timing - fee) > 1e-12:
        raise AssertionError("return decomposition failed")
    following: dict[str, dict[str, float]] = {}
    for horizon in (24, 168, 720):
        values = [compounded(gross[index : min(index + horizon, end)]) for index in selected]
        following[str(horizon)] = {
            "mean": float(np.mean(values)),
            "positive_share": float(np.mean(np.asarray(values) > 0)),
        }
    return {
        "trigger_count": len(selected),
        "half_state_hours": int(mask.sum()),
        "market_return_during_half_state": float(gross[start:end][mask].sum()),
        "timing_contribution": timing,
        "fee_contribution": fee,
        "arithmetic_delta": delta,
        "next_returns": following,
    }


def evaluate(frame: pd.DataFrame) -> dict[str, Any]:
    position, triggers = positions(frame)
    net: dict[str, np.ndarray] = {}
    turn: dict[str, np.ndarray] = {}
    gross = np.empty(0)
    for name, values in position.items():
        net[name], turn[name], gross = returns(frame, values)
    return {
        "training": {name: metric(net[name], turn[name], TRAIN) for name in position},
        "oos": {name: metric(net[name], turn[name], OOS) for name in position},
        "full": {name: metric(net[name], turn[name], FULL) for name in position},
        "breadth": breadth(frame, net["candidate"], net["b1"]),
        "uncertainty": uncertainty(net["candidate"], net["b1"]),
        "diagnostics": {
            "training": diagnostics(
                triggers,
                position,
                net,
                turn,
                gross,
                TRAIN,
            ),
            "oos": diagnostics(
                triggers,
                position,
                net,
                turn,
                gross,
                OOS,
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc", type=Path, required=True)
    parser.add_argument("--eth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {"BTC-USDT": args.btc, "ETH-USDT": args.eth}
    result: dict[str, Any] = {
        "family_id": "spectral-trend-quality-irreversible-downgrade-1h-v1",
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "markets": {},
        "verdict": ("reject_exact_spectral_trend_quality_irreversible_downgrade_family"),
    }
    for market, path in paths.items():
        prefix = load(path, market)
        full = load(path, market, None)
        prefix_position, _ = positions(prefix)
        full_position, _ = positions(full)
        invariant = all(
            np.array_equal(
                prefix_position[name],
                full_position[name][: len(prefix) - 1],
            )
            for name in prefix_position
        )
        if not invariant:
            raise AssertionError(f"future suffix changed positions: {market}")
        result["markets"][market] = evaluate(prefix)
        result["markets"][market]["future_suffix_invariance"] = True
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
