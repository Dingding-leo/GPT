#!/usr/bin/env python3
"""Reproduce the training-only B1 positive-regime stationarity closure."""

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
TRAIN_START = 2_880
TRAIN_END = 17_520
TREND = 2_160
DAY = 24
RESAMPLES = 5_000
SEED = 20_260_731
EXPECTED = {
    "BTC-USDT": "40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0",
    "ETH-USDT": "0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8",
}
ARTIFACT = {"BTC-USDT": 8769605568, "ETH-USDT": 8769619607}


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def load(path: Path, market: str) -> pd.DataFrame:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED[market]:
        raise ValueError(f"{market} immutable CSV hash mismatch")
    frame = pd.read_csv(path, nrows=TRAIN_END, parse_dates=["timestamp"])
    if len(frame) != TRAIN_END or not bool((frame["confirm"] == 1).all()):
        raise ValueError(f"{market} invalid confirmed training prefix")
    if frame["timestamp"].iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError(f"{market} source start changed")
    one_hour = frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)
    if not bool(one_hour.all()):
        raise ValueError(f"{market} prefix is not contiguous 1H")
    return frame


def labels(frame: pd.DataFrame) -> pd.DataFrame:
    close = frame["close"].to_numpy(float)
    opens = frame["open"].to_numpy(float)
    times = frame["timestamp"]
    index = np.arange(len(frame))
    endpoint = np.zeros(len(frame), dtype=bool)
    endpoint[TREND:] = close[TREND:] > close[:-TREND]
    daily = index[(times.dt.hour.to_numpy() == 0) & (index >= TREND)]
    regime = np.full(len(frame), -1, dtype=np.int32)
    current = -1
    previous = False
    starts: dict[int, int] = {}
    ends: dict[int, int] = {}
    for position in daily:
        active = bool(endpoint[position])
        if active and not previous:
            current += 1
            starts[current] = int(position)
        if active:
            regime[position] = current
            ends[current] = int(position)
        previous = active

    eligible = index[
        (times.dt.hour.to_numpy() == 0)
        & (index >= TRAIN_START)
        & (index + 25 < TRAIN_END)
        & endpoint
    ]
    rows: list[dict[str, Any]] = []
    for anchor in eligible:
        decisions = np.arange(anchor, anchor + DAY)
        hourly = opens[decisions + 2] / opens[decisions + 1] - 1
        gross = float(hourly.sum())
        rows.append(
            {
                "anchor": int(anchor),
                "timestamp": times.iloc[anchor].isoformat(),
                "regime": int(regime[anchor]),
                "gross": gross,
                "net": gross - 2 * FEE,
                "adverse": float(np.r_[0.0, np.cumsum(hourly)].min()),
                "regime_start": starts[int(regime[anchor])],
                "regime_end": ends[int(regime[anchor])],
            }
        )
    return pd.DataFrame(rows)


def interval(values: np.ndarray) -> list[float]:
    return np.quantile(values, [0.025, 0.975]).tolist()


def regime_summary(table: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for regime_id, part in table.groupby("regime", sort=True):
        gross = part["gross"].to_numpy(float)
        net = part["net"].to_numpy(float)
        rows.append(
            {
                "regime": int(regime_id),
                "days": len(part),
                "first": part["timestamp"].iloc[0],
                "last": part["timestamp"].iloc[-1],
                "left_censored": bool(part["regime_start"].iloc[0] < TRAIN_START),
                "right_censored": bool(part["regime_end"].iloc[0] > part["anchor"].iloc[-1]),
                "mean_gross": float(gross.mean()),
                "mean_net": float(net.mean()),
                "sum_gross": float(gross.sum()),
                "sum_net": float(net.sum()),
                "mean_adverse": float(part["adverse"].mean()),
                "lag1": (
                    float(np.corrcoef(gross[:-1], gross[1:])[0, 1])
                    if len(gross) >= 4 and np.std(gross[:-1]) > 0 and np.std(gross[1:]) > 0
                    else None
                ),
            }
        )
    return pd.DataFrame(rows)


def bootstrap(regimes: pd.DataFrame) -> dict[str, Any]:
    rng = np.random.default_rng(SEED)
    count = len(regimes)
    picks = rng.integers(0, count, size=(RESAMPLES, count))
    mean_gross = regimes["mean_gross"].to_numpy(float)
    mean_net = regimes["mean_net"].to_numpy(float)
    sum_gross = regimes["sum_gross"].to_numpy(float)
    sum_net = regimes["sum_net"].to_numpy(float)
    days = regimes["days"].to_numpy(float)
    draws = np.empty((RESAMPLES, 6))
    for row, sample in enumerate(picks):
        denominator = days[sample].sum()
        draws[row] = (
            mean_gross[sample].mean(),
            mean_net[sample].mean(),
            np.median(mean_gross[sample]),
            np.median(mean_net[sample]),
            sum_gross[sample].sum() / denominator,
            sum_net[sample].sum() / denominator,
        )
    return {
        "resamples": RESAMPLES,
        "seed": SEED,
        "valid_fraction": 1.0,
        "equal_gross_ci95": interval(draws[:, 0]),
        "equal_net_ci95": interval(draws[:, 1]),
        "median_gross_ci95": interval(draws[:, 2]),
        "median_net_ci95": interval(draws[:, 3]),
        "day_gross_ci95": interval(draws[:, 4]),
        "day_net_ci95": interval(draws[:, 5]),
    }


def breadth(table: pd.DataFrame) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for number in range(6):
        start = TRAIN_START + number * TREND
        part = table[(table["anchor"] >= start) & (table["anchor"] < start + TREND)]
        folds.append(
            {
                "fold": number + 1,
                "observations": len(part),
                "gross": float(part["gross"].mean()) if len(part) else None,
                "net": float(part["net"].mean()) if len(part) else None,
            }
        )
    years = pd.to_datetime(table["timestamp"], utc=True).dt.year
    annual = [
        {
            "year": int(year),
            "gross": float(table.loc[years == year, "gross"].mean()),
            "net": float(table.loc[years == year, "net"].mean()),
        }
        for year in sorted(years.unique())
    ]
    return {
        "folds": folds,
        "positive_gross_folds": sum(
            row["gross"] is not None and row["gross"] > 0 for row in folds
        ),
        "positive_net_folds": sum(row["net"] is not None and row["net"] > 0 for row in folds),
        "years": annual,
        "positive_gross_years": sum(row["gross"] > 0 for row in annual),
        "positive_net_years": sum(row["net"] > 0 for row in annual),
    }


def market_result(path: Path, market: str) -> dict[str, Any]:
    table = labels(load(path, market))
    regimes = regime_summary(table)
    absolute = np.abs(regimes["sum_gross"].to_numpy(float))
    positive = regimes["sum_gross"].clip(lower=0).to_numpy(float)
    loo_equal_gross: list[float] = []
    loo_equal_net: list[float] = []
    loo_day_gross: list[float] = []
    loo_day_net: list[float] = []
    for regime_id in regimes["regime"]:
        remaining_regimes = regimes[regimes["regime"] != regime_id]
        remaining_days = table[table["regime"] != regime_id]
        loo_equal_gross.append(float(remaining_regimes["mean_gross"].mean()))
        loo_equal_net.append(float(remaining_regimes["mean_net"].mean()))
        loo_day_gross.append(float(remaining_days["gross"].mean()))
        loo_day_net.append(float(remaining_days["net"].mean()))
    uncertainty = bootstrap(regimes)
    temporal = breadth(table)
    median_gross = float(regimes["mean_gross"].median())
    median_net = float(regimes["mean_net"].median())
    equal_gross = float(regimes["mean_gross"].mean())
    equal_net = float(regimes["mean_net"].mean())
    day_gross = float(table["gross"].mean())
    day_net = float(table["net"].mean())
    max_absolute = float(absolute.max() / absolute.sum())
    max_positive = float(positive.max() / positive.sum())
    positive_gross = int((regimes["mean_gross"] > 0).sum())
    positive_net = int((regimes["mean_net"] > 0).sum())
    gates = {
        "positive_median": median_gross > 0 and median_net > 0,
        "regime_breadth": positive_gross > len(regimes) / 2
        and positive_net >= len(regimes) / 2,
        "equal_lower_bounds": uncertainty["equal_gross_ci95"][0] > 0
        and uncertainty["equal_net_ci95"][0] > 0,
        "day_lower_bounds": uncertainty["day_gross_ci95"][0] > 0
        and uncertainty["day_net_ci95"][0] > 0,
        "loo_equal": min(loo_equal_gross) > 0 and min(loo_equal_net) > 0,
        "loo_day": min(loo_day_gross) > 0 and min(loo_day_net) > 0,
        "non_dominance": max_absolute <= 0.35 and max_positive <= 0.50,
        "fold_breadth": temporal["positive_gross_folds"] >= 4
        and temporal["positive_net_folds"] >= 4,
        "year_breadth": temporal["positive_gross_years"] >= 2
        and temporal["positive_net_years"] >= 2,
        "valid_bootstrap": uncertainty["valid_fraction"] >= 0.95,
    }
    valid_lag = regimes["lag1"].dropna().to_numpy(float)
    return {
        "market": market,
        "artifact": ARTIFACT[market],
        "csv_sha256": EXPECTED[market],
        "active_labels": len(table),
        "regimes": len(regimes),
        "left_censored": int(regimes["left_censored"].sum()),
        "right_censored": int(regimes["right_censored"].sum()),
        "duration_min_median_max": [
            int(regimes["days"].min()),
            float(regimes["days"].median()),
            int(regimes["days"].max()),
        ],
        "day_weight": {
            "gross": day_gross,
            "net": day_net,
            "adverse": float(table["adverse"].mean()),
            "gross_positive": int((table["gross"] > 0).sum()),
            "net_positive": int((table["net"] > 0).sum()),
            "turnover": float(2 * len(table)),
            "fees": float(2 * FEE * len(table)),
        },
        "regime_weight": {
            "positive_gross": positive_gross,
            "positive_net": positive_net,
            "median_gross": median_gross,
            "median_net": median_net,
            "equal_gross": equal_gross,
            "equal_net": equal_net,
        },
        "concentration": {"max_absolute": max_absolute, "max_positive": max_positive},
        "leave_one_out_minimum": {
            "equal_gross": min(loo_equal_gross),
            "equal_net": min(loo_equal_net),
            "day_gross": min(loo_day_gross),
            "day_net": min(loo_day_net),
        },
        "within_regime_lag1_median": float(np.median(valid_lag)),
        "uncertainty": uncertainty,
        "temporal_breadth": temporal,
        "gates": gates,
        "passes": bool(all(gates.values())),
        "regime_table": regimes.to_dict(orient="records"),
    }


def run(btc: Path, eth: Path) -> dict[str, Any]:
    markets = [market_result(btc, "BTC-USDT"), market_result(eth, "ETH-USDT")]
    accepted = all(market["passes"] for market in markets)
    return {
        "family": "positive-regime-opportunity-stationarity-closure-1h-v1",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "training": [TRAIN_START, TRAIN_END],
        "oos_accessed": False,
        "markets": markets,
        "markets_passing": sum(market["passes"] for market in markets),
        "accepted": accepted,
        "verdict": (
            "support_positive_regime_opportunity_stationarity_premise"
            if accepted
            else "reject_positive_regime_opportunity_stationarity_premise"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc", required=True, type=Path)
    parser.add_argument("--eth", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = json_safe(run(args.btc, args.eth))
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"accepted": result["accepted"], "verdict": result["verdict"]}))


if __name__ == "__main__":
    main()
