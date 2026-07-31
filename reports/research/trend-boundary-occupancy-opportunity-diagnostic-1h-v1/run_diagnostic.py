#!/usr/bin/env python3
"""Reproduce issue #798's training-only boundary-occupancy diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE = 0.0005
PREFIX = 43_441
TRAIN = (2_880, 17_520)
LOOKBACK = 2_160
WEEK = 168
THRESHOLD = 0.25
DRAWS = 5_000
BLOCK = 4
SEED = 20_260_731
HASHES = {
    "BTC-USDT": "40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0",
    "ETH-USDT": "0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def rho(x: np.ndarray, y: np.ndarray) -> float:
    a = pd.Series(x).rank(method="average").to_numpy(float)
    b = pd.Series(y).rank(method="average").to_numpy(float)
    if np.std(a, ddof=1) == 0 or np.std(b, ddof=1) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3 or np.std(x, ddof=1) == 0:
        return float("nan")
    z = (x - x.mean()) / np.std(x, ddof=1)
    return float(np.dot(z, y - y.mean()) / np.dot(z, z))


def load(path: Path, instrument: str) -> pd.DataFrame:
    if sha(path) != HASHES[instrument]:
        raise ValueError(f"{instrument} immutable CSV hash mismatch")
    frame = pd.read_csv(path, parse_dates=["timestamp"]).iloc[:PREFIX].copy()
    if len(frame) != PREFIX or not bool((frame["confirm"] == 1).all()):
        raise ValueError("confirmed-prefix contract failed")
    if frame["timestamp"].iloc[[0, -1]].tolist() != [
        pd.Timestamp("2021-07-24T00:00:00Z"),
        pd.Timestamp("2026-07-08T00:00:00Z"),
    ]:
        raise ValueError("frozen boundaries changed")
    if not bool((frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all()):
        raise ValueError("non-contiguous 1H source")
    return frame.iloc[: TRAIN[1]].copy()


def labels(frame: pd.DataFrame) -> pd.DataFrame:
    times = frame["timestamp"]
    opens = frame["open"].to_numpy(float)
    closes = frame["close"].to_numpy(float)
    log_close = np.log(closes)
    returns = np.r_[np.nan, np.diff(log_close)]
    rms = (
        pd.Series(returns)
        .rolling(WEEK, min_periods=WEEK)
        .apply(lambda row: math.sqrt(float(np.mean(row * row))), raw=True)
        .to_numpy()
    )
    margin = np.full(len(frame), np.nan)
    margin[LOOKBACK:] = np.abs(log_close[LOOKBACK:] - log_close[:-LOOKBACK])
    distance = margin / (math.sqrt(LOOKBACK) * rms)
    near = (distance <= THRESHOLD).astype(float)
    rows = []
    for anchor in range(TRAIN[0], TRAIN[1]):
        time = times.iloc[anchor]
        if time.dayofweek or time.hour or anchor + WEEK + 1 >= TRAIN[1]:
            continue
        window = distance[anchor - WEEK + 1 : anchor + 1]
        if not np.isfinite(window).all():
            continue
        occupancy = float(near[anchor - WEEK + 1 : anchor + 1].mean())
        position = turnover = gross = 0.0
        path = [0.0]
        for decision in range(anchor, anchor + WEEK):
            if times.iloc[decision].hour == 0:
                target = float(closes[decision] > closes[decision - LOOKBACK])
                turnover += abs(target - position)
                position = target
            gross += position * (opens[decision + 2] / opens[decision + 1] - 1)
            path.append(gross)
        turnover += position
        rows.append(
            {
                "anchor_index": anchor,
                "clearance": 1 - occupancy,
                "occupancy": occupancy,
                "gross": gross,
                "net": gross - FEE * turnover,
                "mae": min(path),
                "turnover": turnover,
                "year": int(time.year),
            }
        )
    result = pd.DataFrame(rows)
    if len(result) != 86:
        raise ValueError(f"eligible anchors changed: {len(result)}")
    return result


def breadth(rows: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    folds = []
    for fold in range(6):
        start = TRAIN[0] + fold * LOOKBACK
        part = rows[
            (rows["anchor_index"] >= start) & (rows["anchor_index"] + WEEK + 1 < start + LOOKBACK)
        ]
        folds.append(
            {
                "fold": fold,
                "n": len(part),
                "gross_slope": finite(
                    slope(part["clearance"].to_numpy(), part["gross"].to_numpy())
                ),
                "mae_slope": finite(slope(part["clearance"].to_numpy(), part["mae"].to_numpy())),
            }
        )
    years = []
    for year, part in rows.groupby("year"):
        years.append(
            {
                "year": int(year),
                "n": len(part),
                "gross_slope": finite(
                    slope(part["clearance"].to_numpy(), part["gross"].to_numpy())
                ),
                "mae_slope": finite(slope(part["clearance"].to_numpy(), part["mae"].to_numpy())),
            }
        )
    return folds, years


def summary(rows: pd.DataFrame, sampled: np.ndarray) -> tuple[dict, np.ndarray, np.ndarray]:
    x = rows["clearance"].to_numpy(float)
    gross = rows["gross"].to_numpy(float)
    mae = rows["mae"].to_numpy(float)
    median = float(np.median(x))
    low, high = rows[x <= median], rows[x > median]
    absent, present = rows[rows["occupancy"] == 0], rows[rows["occupancy"] > 0]
    folds, years = breadth(rows)
    gross_draws = np.array([rho(x[index], gross[index]) for index in sampled])
    mae_draws = np.array([rho(x[index], mae[index]) for index in sampled])
    item = {
        "n_anchors": len(rows),
        "occupancy_iqr": float(rows["occupancy"].quantile(0.75) - rows["occupancy"].quantile(0.25)),
        "occupancy_quartiles": [float(rows["occupancy"].quantile(q)) for q in (0.25, 0.5, 0.75)],
        "clearance_median": median,
        "low_n": len(low),
        "high_n": len(high),
        "gross_opportunity_mean": float(gross.mean()),
        "net_payoff_mean": float(rows["net"].mean()),
        "turnover_sum": float(rows["turnover"].sum()),
        "positive_gross_weeks": int((gross > 0).sum()),
        "zero_gross_weeks": int((gross == 0).sum()),
        "gross_rho": rho(x, gross),
        "gross_rho_ci95": np.quantile(gross_draws, [0.025, 0.975]).tolist(),
        "mae_rho": rho(x, mae),
        "mae_rho_ci95": np.quantile(mae_draws, [0.025, 0.975]).tolist(),
        "gross_slope": slope(x, gross),
        "mae_slope": slope(x, mae),
        "high_minus_low_gross_mean": None,
        "high_minus_low_mae_mean": None,
        "descriptive_no_boundary_minus_boundary": {
            "no_boundary_n": len(absent),
            "boundary_n": len(present),
            "gross_mean_delta": float(absent["gross"].mean() - present["gross"].mean()),
            "mae_mean_delta": float(absent["mae"].mean() - present["mae"].mean()),
            "turnover_mean_delta": float(absent["turnover"].mean() - present["turnover"].mean()),
        },
        "folds": folds,
        "years": years,
    }
    if len(high):
        item["high_minus_low_gross_mean"] = float(high["gross"].mean() - low["gross"].mean())
        item["high_minus_low_mae_mean"] = float(high["mae"].mean() - low["mae"].mean())
    item["positive_gross_folds"] = sum(
        x["gross_slope"] is not None and x["gross_slope"] > 0 for x in folds
    )
    item["positive_mae_folds"] = sum(
        x["mae_slope"] is not None and x["mae_slope"] > 0 for x in folds
    )
    item["positive_gross_years"] = sum(
        x["gross_slope"] is not None and x["gross_slope"] > 0 for x in years
    )
    item["positive_mae_years"] = sum(
        x["mae_slope"] is not None and x["mae_slope"] > 0 for x in years
    )
    gates = {
        "gross_rho_positive_lcb": item["gross_rho"] > 0 and item["gross_rho_ci95"][0] > 0,
        "mae_rho_positive_lcb": item["mae_rho"] > 0 and item["mae_rho_ci95"][0] > 0,
        "gross_breadth": (item["positive_gross_folds"] >= 4 and item["positive_gross_years"] >= 2),
        "mae_breadth": item["positive_mae_folds"] >= 4 and item["positive_mae_years"] >= 2,
        "state_variation": (item["occupancy_iqr"] >= 0.10 and len(low) >= 20 and len(high) >= 20),
        "half_ordering": (
            item["high_minus_low_gross_mean"] is not None
            and item["high_minus_low_gross_mean"] > 0
            and item["high_minus_low_mae_mean"] > 0
        ),
    }
    item["gates"] = gates
    item["passes_all"] = all(gates.values())
    return item, gross_draws, mae_draws


def run(btc: Path, eth: Path) -> dict:
    rng = np.random.default_rng(SEED)
    blocks = math.ceil(86 / BLOCK)
    starts = rng.integers(0, 86 - BLOCK + 1, size=(DRAWS, blocks))
    sampled = (starts[..., None] + np.arange(BLOCK)).reshape(DRAWS, -1)[:, :86]
    market_rows = {
        "BTC-USDT": labels(load(btc, "BTC-USDT")),
        "ETH-USDT": labels(load(eth, "ETH-USDT")),
    }
    result = {
        "schema_version": 1,
        "family": "trend-boundary-occupancy-opportunity-diagnostic-1h-v1",
        "issue": 798,
        "classification": "training-only architecture-eligibility diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid": 0,
        "canonical_fee_bps_one_way": 5.0,
        "oos_accessed": False,
        "protocol": {
            "lookback_hours": LOOKBACK,
            "state_hours": WEEK,
            "scaled_distance_threshold": THRESHOLD,
            "training": list(TRAIN),
            "frozen_rows": PREFIX,
            "bootstrap_draws": DRAWS,
            "bootstrap_block_weeks": BLOCK,
            "seed": SEED,
        },
        "markets": {},
    }
    gross_draws, mae_draws = [], []
    for instrument, rows in market_rows.items():
        item, gross, mae = summary(rows, sampled)
        result["markets"][instrument] = {
            "source_csv_sha256": HASHES[instrument],
            "summary": item,
        }
        gross_draws.append(gross)
        mae_draws.append(mae)
    result["common_index"] = {
        "median_gross_rho_point": float(
            np.median([result["markets"][x]["summary"]["gross_rho"] for x in HASHES])
        ),
        "median_gross_rho_ci95": np.quantile(
            np.median(np.vstack(gross_draws), axis=0), [0.025, 0.975]
        ).tolist(),
        "median_mae_rho_point": float(
            np.median([result["markets"][x]["summary"]["mae_rho"] for x in HASHES])
        ),
        "median_mae_rho_ci95": np.quantile(
            np.median(np.vstack(mae_draws), axis=0), [0.025, 0.975]
        ).tolist(),
    }
    result["markets_passing_all"] = sum(
        result["markets"][x]["summary"]["passes_all"] for x in HASHES
    )
    result["verdict"] = (
        "authorize_fresh_cohort_boundary_occupancy_candidate"
        if result["markets_passing_all"] == 2
        else "reject_trend_boundary_occupancy_opportunity_premise"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", required=True, type=Path)
    parser.add_argument("--eth-csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(run(args.btc_csv, args.eth_csv), indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    )


if __name__ == "__main__":
    main()
