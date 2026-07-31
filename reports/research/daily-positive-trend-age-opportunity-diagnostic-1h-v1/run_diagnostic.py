#!/usr/bin/env python3
"""Reproduce issue #806's training-only daily positive-trend age diagnostic."""

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
TRAIN = (2_880, 17_520)
TREND = 2_160
DAY = 24
RESAMPLES = 5_000
BLOCK = 7
SEED = 20_260_731
MIN_DRAW_OBSERVATIONS = 100
MIN_SEGMENT_OBSERVATIONS = 10
EXPECTED = {
    "BTC-USDT": "40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0",
    "ETH-USDT": "0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8",
}
ARTIFACTS = {"BTC-USDT": 8769605568, "ETH-USDT": 8769619607}


def load(path: Path, instrument: str) -> tuple[pd.DataFrame, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED[instrument]:
        raise ValueError(f"{instrument} immutable CSV hash mismatch")

    frame = pd.read_csv(path, nrows=TRAIN[1], parse_dates=["timestamp"])
    if len(frame) != TRAIN[1] or not bool((frame["confirm"] == 1).all()):
        raise ValueError(f"{instrument} training-prefix contract failed")
    if frame["timestamp"].iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError("source start changed")
    delta = frame["timestamp"].diff().dropna()
    if not bool((delta == pd.Timedelta(hours=1)).all()):
        raise ValueError(f"{instrument} training prefix is not contiguous 1H")
    return frame, digest


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    left = pd.Series(x).rank(method="average").to_numpy(float)
    right = pd.Series(y).rank(method="average").to_numpy(float)
    if np.std(left, ddof=1) <= 0 or np.std(right, ddof=1) <= 0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])


def standardized_slope(
    x: np.ndarray,
    y: np.ndarray,
    minimum_observations: int = 3,
) -> float:
    if len(x) < minimum_observations or np.std(x, ddof=1) <= 0:
        return float("nan")
    standardized = (x - np.mean(x)) / np.std(x, ddof=1)
    design = np.c_[np.ones(len(standardized)), standardized]
    return float(np.linalg.lstsq(design, y, rcond=None)[0][1])


def finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def build_table(
    path: Path,
    instrument: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame, digest = load(path, instrument)
    times = frame["timestamp"]
    opens = frame["open"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    indices = np.arange(len(frame))

    endpoint = np.zeros(len(frame), dtype=np.int8)
    endpoint[TREND:] = close[TREND:] > close[:-TREND]

    daily_indices = indices[(times.dt.hour.to_numpy() == 0) & (indices >= TREND)]
    ages = np.zeros(len(frame), dtype=np.int32)
    previous_age = 0
    for index in daily_indices:
        if endpoint[index]:
            previous_age += 1
            ages[index] = previous_age
        else:
            previous_age = 0

    anchors = indices[
        (times.dt.hour.to_numpy() == 0) & (indices >= TRAIN[0]) & (indices + 25 < TRAIN[1])
    ]
    if not np.all(np.diff(anchors) == DAY):
        raise ValueError("eligible daily calendar changed")

    rows: list[dict[str, Any]] = []
    positive_regimes = 0
    for anchor in anchors:
        active = bool(endpoint[anchor])
        if active and ages[anchor] == 1:
            positive_regimes += 1

        decisions = np.arange(anchor, anchor + DAY)
        hourly = opens[decisions + 2] / opens[decisions + 1] - 1
        gross = float(hourly.sum())
        rows.append(
            {
                "anchor_index": int(anchor),
                "anchor_timestamp": times.iloc[anchor].isoformat(),
                "active_at_anchor": active,
                "age_days": int(ages[anchor]),
                "state": float(np.log1p(ages[anchor])) if active else float("nan"),
                "gross_opportunity": gross,
                "net_payoff": gross - 2 * FEE,
                "adverse_excursion": float(np.r_[0, np.cumsum(hourly)].min()),
                "turnover": 2.0,
                "fees": 2 * FEE,
            }
        )

    table = pd.DataFrame(rows)
    return table, {
        "instrument": instrument,
        "artifact_id": ARTIFACTS[instrument],
        "csv_sha256": digest,
        "calendar_anchors": len(table),
        "active_anchors": int(table["active_at_anchor"].sum()),
        "positive_regimes": positive_regimes,
        "first_anchor": table["anchor_timestamp"].iloc[0],
        "last_anchor": table["anchor_timestamp"].iloc[-1],
    }


def target_statistics(rows: pd.DataFrame) -> dict[str, float]:
    state = rows["state"].to_numpy(float)
    gross = rows["gross_opportunity"].to_numpy(float)
    adverse = rows["adverse_excursion"].to_numpy(float)
    return {
        "gross_spearman": spearman(state, gross),
        "adverse_spearman": spearman(state, adverse),
        "gross_slope_per_state_sd": standardized_slope(state, gross),
        "adverse_slope_per_state_sd": standardized_slope(state, adverse),
    }


def segment_slope(rows: pd.DataFrame, target: str) -> float | None:
    value = standardized_slope(
        rows["state"].to_numpy(float),
        rows[target].to_numpy(float),
        MIN_SEGMENT_OBSERVATIONS,
    )
    return finite_or_none(value)


def breadth(rows: pd.DataFrame) -> dict[str, Any]:
    fold_rows: list[dict[str, Any]] = []
    for number in range(6):
        start = TRAIN[0] + number * TREND
        part = rows[(rows["anchor_index"] >= start) & (rows["anchor_index"] < start + TREND)]
        fold_rows.append(
            {
                "fold": number + 1,
                "start_index": start,
                "end_index_exclusive": start + TREND,
                "observations": len(part),
                "gross_slope": segment_slope(part, "gross_opportunity"),
                "adverse_slope": segment_slope(part, "adverse_excursion"),
            }
        )

    years = pd.to_datetime(rows["anchor_timestamp"], utc=True).dt.year
    year_rows: list[dict[str, Any]] = []
    for year in sorted(years.unique()):
        part = rows[years == year]
        year_rows.append(
            {
                "year": int(year),
                "observations": len(part),
                "gross_slope": segment_slope(part, "gross_opportunity"),
                "adverse_slope": segment_slope(part, "adverse_excursion"),
            }
        )

    def positive(items: list[dict[str, Any]], key: str) -> int:
        return sum(item[key] is not None and item[key] > 0 for item in items)

    def supported(items: list[dict[str, Any]], key: str) -> int:
        return sum(item[key] is not None for item in items)

    return {
        "folds": fold_rows,
        "positive_gross_folds": positive(fold_rows, "gross_slope"),
        "positive_adverse_folds": positive(fold_rows, "adverse_slope"),
        "supported_gross_folds": supported(fold_rows, "gross_slope"),
        "supported_adverse_folds": supported(fold_rows, "adverse_slope"),
        "years": year_rows,
        "positive_gross_years": positive(year_rows, "gross_slope"),
        "positive_adverse_years": positive(year_rows, "adverse_slope"),
        "supported_gross_years": supported(year_rows, "gross_slope"),
        "supported_adverse_years": supported(year_rows, "adverse_slope"),
    }


def descriptive(rows: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    state = rows["state"].to_numpy(float)
    age = rows["age_days"].to_numpy(float)
    gross = rows["gross_opportunity"].to_numpy(float)
    net = rows["net_payoff"].to_numpy(float)
    adverse = rows["adverse_excursion"].to_numpy(float)

    quantiles = np.quantile(state, [0, 0.25, 0.5, 0.75, 1])
    age_quantiles = np.quantile(age, [0, 0.25, 0.5, 0.75, 1])
    median = float(quantiles[2])
    low = rows[rows["state"] <= median]
    high = rows[rows["state"] > median]

    distribution = {
        "state_quantiles": dict(
            zip(
                ("min", "q25", "median", "q75", "max"),
                quantiles,
                strict=True,
            )
        ),
        "state_iqr": float(quantiles[3] - quantiles[1]),
        "age_quantiles_days": dict(
            zip(
                ("min", "q25", "median", "q75", "max"),
                age_quantiles,
                strict=True,
            )
        ),
        "gross_mean": float(gross.mean()),
        "gross_median": float(np.median(gross)),
        "gross_positive_days": int((gross > 0).sum()),
        "gross_zero_days": int((gross == 0).sum()),
        "net_mean": float(net.mean()),
        "net_median": float(np.median(net)),
        "net_positive_days": int((net > 0).sum()),
        "adverse_mean": float(adverse.mean()),
        "adverse_median": float(np.median(adverse)),
        "turnover_total": float(rows["turnover"].sum()),
        "fees_total": float(rows["fees"].sum()),
        "max_absolute_gross_share": float(np.abs(gross).max() / np.abs(gross).sum()),
        "max_absolute_net_share": float(np.abs(net).max() / np.abs(net).sum()),
    }
    split = {
        "state_median": median,
        "low_observations": len(low),
        "high_observations": len(high),
        "low_gross_mean": float(low["gross_opportunity"].mean()),
        "high_gross_mean": float(high["gross_opportunity"].mean()),
        "high_minus_low_gross": float(
            high["gross_opportunity"].mean() - low["gross_opportunity"].mean()
        ),
        "low_adverse_mean": float(low["adverse_excursion"].mean()),
        "high_adverse_mean": float(high["adverse_excursion"].mean()),
        "high_minus_low_adverse": float(
            high["adverse_excursion"].mean() - low["adverse_excursion"].mean()
        ),
        "low_net_mean": float(low["net_payoff"].mean()),
        "high_net_mean": float(high["net_payoff"].mean()),
        "high_minus_low_net": float(high["net_payoff"].mean() - low["net_payoff"].mean()),
    }
    return distribution, split


def common_calendar_samples(length: int) -> np.ndarray:
    generator = np.random.default_rng(SEED)
    block_count = math.ceil(length / BLOCK)
    starts = generator.integers(
        0,
        length - BLOCK + 1,
        size=(RESAMPLES, block_count),
    )
    return (starts[..., None] + np.arange(BLOCK)).reshape(RESAMPLES, -1)[:, :length]


def bootstrap_draws(table: pd.DataFrame, samples: np.ndarray) -> np.ndarray:
    draws = np.full((len(samples), 4), np.nan)
    for number, indices in enumerate(samples):
        rows = table.iloc[indices]
        rows = rows[rows["active_at_anchor"]]
        state = rows["state"].to_numpy(float)
        if len(rows) < MIN_DRAW_OBSERVATIONS or np.std(state, ddof=1) <= 0:
            continue
        draws[number] = list(target_statistics(rows).values())
    return draws


def summarize_market(
    table: pd.DataFrame,
    metadata: dict[str, Any],
    samples: np.ndarray,
) -> tuple[dict[str, Any], np.ndarray]:
    rows = table[table["active_at_anchor"]].copy()
    point = target_statistics(rows)
    draws = bootstrap_draws(table, samples)
    valid = np.all(np.isfinite(draws), axis=1)
    valid_count = int(valid.sum())
    valid_fraction = float(valid.mean())
    ci95 = {
        name: np.quantile(draws[valid, column], [0.025, 0.975]).tolist()
        for column, name in enumerate(point)
    }

    distribution, median_split = descriptive(rows)
    temporal = breadth(rows)
    required_years = math.ceil(2 * len(temporal["years"]) / 3)
    gates = {
        "gross_positive_lower_bound": point["gross_spearman"] > 0 and ci95["gross_spearman"][0] > 0,
        "adverse_positive_lower_bound": point["adverse_spearman"] > 0
        and ci95["adverse_spearman"][0] > 0,
        "positive_economic_slopes": point["gross_slope_per_state_sd"] > 0
        and point["adverse_slope_per_state_sd"] > 0,
        "fold_breadth": temporal["positive_gross_folds"] >= 4
        and temporal["positive_adverse_folds"] >= 4,
        "year_breadth": temporal["positive_gross_years"] >= required_years
        and temporal["positive_adverse_years"] >= required_years,
        "state_dispersion": distribution["state_iqr"] >= 0.50,
        "median_partition_support": median_split["low_observations"] >= 100
        and median_split["high_observations"] >= 100,
        "median_partition_economics": median_split["high_minus_low_gross"] > 0
        and median_split["high_minus_low_adverse"] > 0,
        "valid_bootstrap_fraction": valid_fraction >= 0.95,
    }
    return {
        **metadata,
        "point": point,
        "ci95": ci95,
        "valid_bootstrap_draws": valid_count,
        "valid_bootstrap_fraction": valid_fraction,
        "distribution": distribution,
        "median_split": median_split,
        "breadth": temporal,
        "gates": gates,
        "passes_market_gates": bool(all(gates.values())),
    }, draws


def common_summary(
    bitcoin: dict[str, Any],
    ether: dict[str, Any],
    bitcoin_draws: np.ndarray,
    ether_draws: np.ndarray,
) -> dict[str, Any]:
    valid = np.all(np.isfinite(bitcoin_draws), axis=1) & np.all(np.isfinite(ether_draws), axis=1)
    common_draws = np.median(
        np.stack((bitcoin_draws, ether_draws), axis=2),
        axis=2,
    )
    names = (
        "gross_spearman",
        "adverse_spearman",
        "gross_slope",
        "adverse_slope",
    )
    point_names = (
        "gross_spearman",
        "adverse_spearman",
        "gross_slope_per_state_sd",
        "adverse_slope_per_state_sd",
    )
    summary: dict[str, Any] = {
        "valid_draws": int(valid.sum()),
        "valid_fraction": float(valid.mean()),
    }
    for column, (name, point_name) in enumerate(zip(names, point_names, strict=True)):
        summary[f"{name}_point"] = float(
            np.median((bitcoin["point"][point_name], ether["point"][point_name]))
        )
        summary[f"{name}_ci95"] = np.quantile(
            common_draws[valid, column],
            [0.025, 0.975],
        ).tolist()
    return summary


def run(btc_path: Path, eth_path: Path) -> dict[str, Any]:
    btc_table, btc_metadata = build_table(btc_path, "BTC-USDT")
    eth_table, eth_metadata = build_table(eth_path, "ETH-USDT")
    if not np.array_equal(btc_table["anchor_index"], eth_table["anchor_index"]):
        raise ValueError("market daily calendars differ")

    samples = common_calendar_samples(len(btc_table))
    btc_summary, btc_draws = summarize_market(btc_table, btc_metadata, samples)
    eth_summary, eth_draws = summarize_market(eth_table, eth_metadata, samples)
    common = common_summary(btc_summary, eth_summary, btc_draws, eth_draws)
    common_gate = (
        common["valid_fraction"] >= 0.95
        and common["gross_spearman_ci95"][0] > 0
        and common["adverse_spearman_ci95"][0] > 0
    )
    accepted = (
        btc_summary["passes_market_gates"] and eth_summary["passes_market_gates"] and common_gate
    )
    return {
        "family_id": "daily-positive-trend-age-opportunity-diagnostic-1h-v1",
        "issue": 806,
        "classification": "training-only architecture-eligibility diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "bar": "immutable public confirmed OKX SPOT 1H",
        "fee_one_way": FEE,
        "training_indices": list(TRAIN),
        "oos_accessed": False,
        "resamples": RESAMPLES,
        "block_daily_observations": BLOCK,
        "seed": SEED,
        "markets": [btc_summary, eth_summary],
        "common_index": common,
        "common_index_gate": common_gate,
        "accepted": accepted,
        "verdict": (
            "support_daily_positive_trend_age_opportunity_premise"
            if accepted
            else "reject_daily_positive_trend_age_opportunity_premise"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc", type=Path, required=True)
    parser.add_argument("--eth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    result = run(arguments.btc, arguments.eth)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"accepted": result["accepted"], "verdict": result["verdict"]}))


if __name__ == "__main__":
    main()
