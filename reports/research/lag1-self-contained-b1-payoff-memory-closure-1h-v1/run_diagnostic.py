#!/usr/bin/env python3
"""Reproduce issue #795's training-only lag-1 B1-payoff memory closure."""

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
PREFIX = 43_441
TRAIN = (2_880, 17_520)
RESAMPLES = 5_000
BLOCK = 4
SEED = 20_260_731
EXPECTED = {
    "BTC-USDT": "40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0",
    "ETH-USDT": "0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8",
}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def daily_b1(times: pd.Series, closes: np.ndarray) -> np.ndarray:
    endpoint = np.zeros(len(closes), dtype=np.int8)
    endpoint[2_160:] = (closes[2_160:] > closes[:-2_160]).astype(np.int8)
    signal = np.zeros(len(closes), dtype=np.int8)
    held = 0
    for index in range(2_160, len(closes)):
        if times.iloc[index].hour == 0:
            held = int(endpoint[index])
        signal[index] = held
    return signal


def weekly_labels(path: Path, instrument: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if file_hash(path) != EXPECTED[instrument]:
        raise ValueError(f"{instrument} immutable CSV hash mismatch")
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    prefix = frame.iloc[:PREFIX]
    if len(prefix) != PREFIX or not bool((prefix["confirm"] == 1).all()):
        raise ValueError(f"{instrument} confirmed-prefix contract failed")
    if not bool((prefix["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all()):
        raise ValueError(f"{instrument} is not contiguous 1H")
    if prefix["timestamp"].iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError("source start changed")
    if prefix["timestamp"].iloc[-1] != pd.Timestamp("2026-07-08T00:00:00Z"):
        raise ValueError("frozen prefix end changed")

    # No statistic below can access a row at or after TRAIN[1].
    frame = frame.iloc[: TRAIN[1]].copy()
    times = frame["timestamp"]
    opens = frame["open"].to_numpy(float)
    signal = daily_b1(times, frame["close"].to_numpy(float))
    indices = np.arange(len(frame))
    anchors = indices[
        (times.dt.dayofweek.to_numpy() == 0)
        & (times.dt.hour.to_numpy() == 0)
        & (indices >= TRAIN[0] + 169)
    ]
    if len(anchors) != 86 or not np.all(np.diff(anchors) == 168):
        raise ValueError("eligible Monday anchors changed")

    labels = []
    turnovers = []
    for anchor in anchors:
        decisions = np.arange(anchor - 169, anchor - 1)
        positions = signal[decisions].astype(float)
        gross = float(np.sum(positions * (opens[decisions + 2] / opens[decisions + 1] - 1)))
        turnover = float(positions[0] + np.abs(np.diff(positions)).sum() + positions[-1])
        labels.append(gross - FEE * turnover)
        turnovers.append(turnover)
    return np.asarray(labels), np.asarray(turnovers), anchors


def stats(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    positive = x > 0
    if (
        len(x) < 2
        or np.std(x, ddof=1) <= 0
        or np.std(y, ddof=1) <= 0
        or not np.any(positive)
        or not np.any(~positive)
    ):
        raise ValueError("undefined frozen statistic")
    return np.array(
        [
            np.corrcoef(x, y)[0, 1],
            np.mean(y[positive] > 0) - np.mean(y[~positive] > 0),
            np.mean(y[positive]) - np.mean(y[~positive]),
        ],
        dtype=float,
    )


def breadth(x: np.ndarray, y: np.ndarray, next_anchors: np.ndarray) -> dict[str, Any]:
    folds = []
    for fold in range(6):
        start = TRAIN[0] + fold * 2_160
        selected = (next_anchors >= start) & (next_anchors < start + 2_160)
        value = None
        enough = selected.sum() >= 4
        variable = np.std(x[selected], ddof=1) > 0 and np.std(y[selected], ddof=1) > 0
        if enough and variable:
            value = float(np.corrcoef(x[selected], y[selected])[0, 1])
        folds.append(value)
    years = []
    next_times = pd.Timestamp("2021-07-24T00:00:00Z") + pd.to_timedelta(next_anchors, unit="h")
    for year in (2021, 2022, 2023):
        selected = np.asarray(next_times.year == year)
        value = None
        enough = selected.sum() >= 4
        variable = np.std(x[selected], ddof=1) > 0 and np.std(y[selected], ddof=1) > 0
        if enough and variable:
            value = float(np.corrcoef(x[selected], y[selected])[0, 1])
        years.append(value)
    return {
        "fold_correlations": folds,
        "positive_folds": sum(value is not None and value > 0 for value in folds),
        "year_correlations": years,
        "positive_years": sum(value is not None and value > 0 for value in years),
    }


def block_indices(pair_count: int) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    blocks = math.ceil(pair_count / BLOCK)
    starts = rng.integers(0, pair_count - BLOCK + 1, size=(RESAMPLES, blocks))
    return (starts[..., None] + np.arange(BLOCK)).reshape(RESAMPLES, -1)[:, :pair_count]


def market_result(path: Path, instrument: str, sampled: np.ndarray) -> dict[str, Any]:
    labels, turnovers, anchors = weekly_labels(path, instrument)
    x, y = labels[:-1], labels[1:]
    point = stats(x, y)
    draws = np.vstack([stats(x[index], y[index]) for index in sampled])
    positive = x > 0
    transitions = {
        "positive_to_positive": int(np.sum(positive & (y > 0))),
        "positive_to_nonpositive": int(np.sum(positive & (y <= 0))),
        "nonpositive_to_positive": int(np.sum(~positive & (y > 0))),
        "nonpositive_to_nonpositive": int(np.sum(~positive & (y <= 0))),
    }
    return {
        "instrument": instrument,
        "weekly_observations": len(labels),
        "pairs": len(x),
        "lagged_positive": int(positive.sum()),
        "lagged_nonpositive": int((~positive).sum()),
        "point": dict(zip(("correlation", "sign_delta", "mean_delta"), point, strict=True)),
        "ci95": {
            name: np.quantile(draws[:, column], [0.025, 0.975]).tolist()
            for column, name in enumerate(("correlation", "sign_delta", "mean_delta"))
        },
        "transitions": transitions,
        "breadth": breadth(x, y, anchors[1:]),
        "mean_weekly_payoff": float(labels.mean()),
        "median_weekly_payoff": float(np.median(labels)),
        "embedded_turnover": float(turnovers.sum()),
        "embedded_fees": float(FEE * turnovers.sum()),
        "max_absolute_payoff_share": float(np.abs(labels).max() / np.abs(labels).sum()),
        "bootstrap_draws": draws,
    }


def clean(item: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in item.items() if key != "bootstrap_draws"}


def run(btc: Path, eth: Path) -> dict[str, Any]:
    sampled = block_indices(85)
    markets = [market_result(btc, "BTC-USDT", sampled), market_result(eth, "ETH-USDT", sampled)]
    common_draws = np.median(np.stack([item["bootstrap_draws"] for item in markets]), axis=0)
    metric_names = ("correlation", "sign_delta", "mean_delta")
    point_rows = np.vstack([[item["point"][name] for name in metric_names] for item in markets])
    common_point = np.median(point_rows, axis=0)
    common_ci = np.vstack(
        [np.quantile(common_draws[:, column], [0.025, 0.975]) for column in range(3)]
    )

    def market_passes(item: dict[str, Any]) -> bool:
        point = item["point"]
        ci = item["ci95"]
        return (
            all(point[name] > 0 for name in metric_names)
            and all(ci[name][0] > 0 for name in metric_names)
            and item["breadth"]["positive_folds"] >= 4
            and item["breadth"]["positive_years"] >= 2
            and item["lagged_positive"] >= 20
            and item["lagged_nonpositive"] >= 20
            and item["max_absolute_payoff_share"] <= 0.25
        )

    accepted = all(market_passes(item) for item in markets) and bool(
        np.all(common_ci[:, 0] > 0)
    )
    return {
        "family_id": "lag1-self-contained-b1-payoff-memory-closure-1h-v1",
        "issue": 795,
        "candidate_count": 0,
        "diagnostic_count": 1,
        "sample": {"training": list(TRAIN), "oos_accessed": False},
        "markets": [clean(item) for item in markets],
        "common": {
            "point": dict(zip(metric_names, common_point, strict=True)),
            "ci95": {
                name: common_ci[column].tolist()
                for column, name in enumerate(metric_names)
            },
        },
        "accepted": accepted,
        "verdict": (
            "support_lag1_self_contained_b1_payoff_memory_premise"
            if accepted
            else "reject_lag1_self_contained_b1_payoff_memory_premise"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.btc_csv, args.eth_csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
