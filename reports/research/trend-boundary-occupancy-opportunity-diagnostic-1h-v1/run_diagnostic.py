#!/usr/bin/env python3
"""Audit issue #798's frozen feature-window eligibility boundary."""

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


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def finite(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def rho(x: np.ndarray, y: np.ndarray) -> float:
    left = pd.Series(x).rank(method="average").to_numpy(float)
    right = pd.Series(y).rank(method="average").to_numpy(float)
    if np.std(left, ddof=1) == 0 or np.std(right, ddof=1) == 0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])


def slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3 or np.std(x, ddof=1) == 0:
        return float("nan")
    standardized = (x - x.mean()) / np.std(x, ddof=1)
    return float(np.dot(standardized, y - y.mean()) / np.dot(standardized, standardized))


def load(path: Path, instrument: str) -> pd.DataFrame:
    if sha256(path) != HASHES[instrument]:
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


def labels(frame: pd.DataFrame, require_feature_inside_training: bool) -> pd.DataFrame:
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
        feature_start = anchor - WEEK + 1
        if require_feature_inside_training and feature_start < TRAIN[0]:
            continue
        window = distance[feature_start : anchor + 1]
        if not np.isfinite(window).all():
            continue
        occupancy = float(near[feature_start : anchor + 1].mean())
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
                "anchor_timestamp": time.isoformat(),
                "feature_start_index": feature_start,
                "feature_start_timestamp": times.iloc[feature_start].isoformat(),
                "clearance": 1 - occupancy,
                "occupancy": occupancy,
                "gross": gross,
                "net": gross - FEE * turnover,
                "mae": min(path),
                "turnover": turnover,
                "year": int(time.year),
            }
        )
    return pd.DataFrame(rows)


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


def sampled_indices(length: int) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    blocks = math.ceil(length / BLOCK)
    starts = rng.integers(0, length - BLOCK + 1, size=(DRAWS, blocks))
    return (starts[..., None] + np.arange(BLOCK)).reshape(DRAWS, -1)[:, :length]


def summary(rows: pd.DataFrame) -> tuple[dict, np.ndarray, np.ndarray]:
    sampled = sampled_indices(len(rows))
    x = rows["clearance"].to_numpy(float)
    gross = rows["gross"].to_numpy(float)
    mae = rows["mae"].to_numpy(float)
    median = float(np.median(x))
    low = rows[x <= median]
    high = rows[x > median]
    folds, years = breadth(rows)
    gross_draws = np.array([rho(x[index], gross[index]) for index in sampled])
    mae_draws = np.array([rho(x[index], mae[index]) for index in sampled])
    item = {
        "n_anchors": len(rows),
        "first_anchor": rows["anchor_timestamp"].iloc[0],
        "first_feature_start": rows["feature_start_timestamp"].iloc[0],
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
        "folds": folds,
        "years": years,
    }
    item["positive_gross_folds"] = sum(
        row["gross_slope"] is not None and row["gross_slope"] > 0 for row in folds
    )
    item["positive_mae_folds"] = sum(
        row["mae_slope"] is not None and row["mae_slope"] > 0 for row in folds
    )
    item["positive_gross_years"] = sum(
        row["gross_slope"] is not None and row["gross_slope"] > 0 for row in years
    )
    item["positive_mae_years"] = sum(
        row["mae_slope"] is not None and row["mae_slope"] > 0 for row in years
    )
    gates = {
        "gross_rho_positive_lcb": item["gross_rho"] > 0 and item["gross_rho_ci95"][0] > 0,
        "mae_rho_positive_lcb": item["mae_rho"] > 0 and item["mae_rho_ci95"][0] > 0,
        "gross_breadth": item["positive_gross_folds"] >= 4 and item["positive_gross_years"] >= 2,
        "mae_breadth": item["positive_mae_folds"] >= 4 and item["positive_mae_years"] >= 2,
        "state_variation": item["occupancy_iqr"] >= 0.10 and len(low) >= 20 and len(high) >= 20,
    }
    item["gates"] = gates
    item["passes_all"] = all(gates.values())
    return item, gross_draws, mae_draws


def common_index(market_summaries: dict[str, dict], draws: dict[str, tuple]) -> dict:
    gross = np.median(np.vstack([draws[key][0] for key in HASHES]), axis=0)
    mae = np.median(np.vstack([draws[key][1] for key in HASHES]), axis=0)
    return {
        "median_gross_rho_point": float(
            np.median([market_summaries[key]["gross_rho"] for key in HASHES])
        ),
        "median_gross_rho_ci95": np.quantile(gross, [0.025, 0.975]).tolist(),
        "median_mae_rho_point": float(
            np.median([market_summaries[key]["mae_rho"] for key in HASHES])
        ),
        "median_mae_rho_ci95": np.quantile(mae, [0.025, 0.975]).tolist(),
    }


def run(btc: Path, eth: Path) -> dict:
    paths = {"BTC-USDT": btc, "ETH-USDT": eth}
    original = {}
    corrected = {}
    original_draws = {}
    corrected_draws = {}
    excluded = {}
    for instrument, path in paths.items():
        frame = load(path, instrument)
        prior_rows = labels(frame, require_feature_inside_training=False)
        fixed_rows = labels(frame, require_feature_inside_training=True)
        prior_summary, prior_gross, prior_mae = summary(prior_rows)
        fixed_summary, fixed_gross, fixed_mae = summary(fixed_rows)
        original[instrument] = prior_summary
        corrected[instrument] = fixed_summary
        original_draws[instrument] = (prior_gross, prior_mae)
        corrected_draws[instrument] = (fixed_gross, fixed_mae)
        removed = prior_rows[~prior_rows["anchor_index"].isin(fixed_rows["anchor_index"])]
        excluded[instrument] = removed.to_dict(orient="records")
    original_common = common_index(original, original_draws)
    corrected_common = common_index(corrected, corrected_draws)
    return {
        "schema_version": 1,
        "family": "trend-boundary-occupancy-opportunity-diagnostic-1h-v1",
        "issue": 798,
        "audit": "strict-training-feature-window-eligibility",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid": 0,
        "canonical_fee_bps_one_way": 5.0,
        "oos_accessed": False,
        "source_csv_sha256": HASHES,
        "protocol": {
            "frozen_text": (
                "complete feature window and complete 168H target lie strictly inside training"
            ),
            "training": list(TRAIN),
            "lookback_hours": LOOKBACK,
            "state_hours": WEEK,
            "scaled_distance_threshold": THRESHOLD,
            "bootstrap_draws": DRAWS,
            "bootstrap_block_weeks": BLOCK,
            "seed": SEED,
        },
        "prior_terminal_evidence": {
            "head": "d574491e00913fe56288f25ab47357eeeebe5ec4",
            "markets": original,
            "common_index": original_common,
        },
        "corrected_evidence": {
            "eligibility_rule": "anchor - 167 >= 2880",
            "markets": corrected,
            "common_index": corrected_common,
            "markets_passing_all": sum(corrected[key]["passes_all"] for key in HASHES),
            "verdict": "reject_trend_boundary_occupancy_opportunity_premise",
        },
        "excluded_rows": excluded,
        "verdict_changed": False,
        "canonical_strategy_changed": False,
        "strategy_metrics": {
            "train": "not computed; candidate_count=0",
            "oos": "not accessed",
            "full": "not computed; candidate_count=0",
            "benchmark_comparison": "not applicable; diagnostic target sleeves only",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", required=True, type=Path)
    parser.add_argument("--eth-csv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.write_text(
        json.dumps(
            run(args.btc_csv, args.eth_csv),
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
