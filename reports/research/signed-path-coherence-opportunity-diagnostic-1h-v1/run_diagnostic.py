#!/usr/bin/env python3
"""Reproduce issue #803's training-only signed path-coherence diagnostic."""

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
WEEK = 168
RESAMPLES = 5_000
BLOCK = 4
SEED = 20_260_731
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


def daily_b1(times: pd.Series, close: np.ndarray) -> np.ndarray:
    endpoint = np.zeros(len(close), dtype=np.int8)
    endpoint[TREND:] = close[TREND:] > close[:-TREND]
    position = np.zeros(len(close), dtype=np.int8)
    held = 0
    for index in range(TREND, len(close)):
        if times.iloc[index].hour == 0:
            held = int(endpoint[index])
        position[index] = held
    return position


def build_table(path: Path, instrument: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame, digest = load(path, instrument)
    times = frame["timestamp"]
    opens = frame["open"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    log_close = np.log(close)
    hourly_log = np.r_[np.nan, np.diff(log_close)]
    position = daily_b1(times, close)
    index = np.arange(len(frame))
    anchors = index[
        (times.dt.dayofweek.to_numpy() == 0)
        & (times.dt.hour.to_numpy() == 0)
        & (index - 167 >= TRAIN[0])
        & (index + 169 < TRAIN[1])
    ]
    if len(anchors) != 85 or not np.all(np.diff(anchors) == WEEK):
        raise ValueError("eligible weekly calendar changed")

    rows: list[dict[str, Any]] = []
    for anchor in anchors:
        denominator = float(np.abs(hourly_log[anchor - 167 : anchor + 1]).sum())
        if not math.isfinite(denominator) or denominator <= 0:
            raise ValueError("undefined path-coherence denominator")
        coherence = float((log_close[anchor] - log_close[anchor - WEEK]) / denominator)
        decisions = np.arange(anchor, anchor + WEEK)
        held = position[decisions].astype(float)
        hourly = held * (opens[decisions + 2] / opens[decisions + 1] - 1)
        turnover = float(held[0] + np.abs(np.diff(held)).sum() + held[-1])
        rows.append(
            {
                "anchor_index": int(anchor),
                "anchor_timestamp": times.iloc[anchor].isoformat(),
                "coherence": coherence,
                "active_at_anchor": bool(position[anchor] == 1),
                "gross_opportunity": float(hourly.sum()),
                "net_payoff": float(hourly.sum() - FEE * turnover),
                "adverse_excursion": float(np.r_[0, np.cumsum(hourly)].min()),
                "turnover": turnover,
                "fees": FEE * turnover,
                "long_hours": int(held.sum()),
            }
        )
    table = pd.DataFrame(rows)
    return table, {
        "instrument": instrument,
        "artifact_id": ARTIFACTS[instrument],
        "csv_sha256": digest,
        "calendar_anchors": len(table),
        "active_anchors": int(table["active_at_anchor"].sum()),
        "first_anchor": table["anchor_timestamp"].iloc[0],
        "last_anchor": table["anchor_timestamp"].iloc[-1],
    }


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    left = pd.Series(x).rank(method="average").to_numpy(float)
    right = pd.Series(y).rank(method="average").to_numpy(float)
    if len(x) < 3 or np.std(left, ddof=1) <= 0 or np.std(right, ddof=1) <= 0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])


def standardized_slope(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3 or np.std(x, ddof=1) <= 0:
        return float("nan")
    standardized = (x - np.mean(x)) / np.std(x, ddof=1)
    design = np.c_[np.ones(len(standardized)), standardized]
    return float(np.linalg.lstsq(design, y, rcond=None)[0][1])


def finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def target_statistics(rows: pd.DataFrame) -> dict[str, float]:
    x = rows["coherence"].to_numpy(float)
    gross = rows["gross_opportunity"].to_numpy(float)
    adverse = rows["adverse_excursion"].to_numpy(float)
    return {
        "gross_spearman": spearman(x, gross),
        "adverse_spearman": spearman(x, adverse),
        "gross_slope_per_state_sd": standardized_slope(x, gross),
        "adverse_slope_per_state_sd": standardized_slope(x, adverse),
    }


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
                "gross_slope": finite_or_none(
                    standardized_slope(
                        part["coherence"].to_numpy(float),
                        part["gross_opportunity"].to_numpy(float),
                    )
                ),
                "adverse_slope": finite_or_none(
                    standardized_slope(
                        part["coherence"].to_numpy(float),
                        part["adverse_excursion"].to_numpy(float),
                    )
                ),
            }
        )

    years = pd.to_datetime(rows["anchor_timestamp"], utc=True).dt.year
    year_rows: list[dict[str, Any]] = []
    for year in (2021, 2022, 2023):
        part = rows[years == year]
        year_rows.append(
            {
                "year": year,
                "observations": len(part),
                "gross_slope": finite_or_none(
                    standardized_slope(
                        part["coherence"].to_numpy(float),
                        part["gross_opportunity"].to_numpy(float),
                    )
                ),
                "adverse_slope": finite_or_none(
                    standardized_slope(
                        part["coherence"].to_numpy(float),
                        part["adverse_excursion"].to_numpy(float),
                    )
                ),
            }
        )

    def positive(items: list[dict[str, Any]], key: str) -> int:
        return sum(item[key] is not None and item[key] > 0 for item in items)

    fold_end = TRAIN[0] + 6 * TREND
    return {
        "folds": fold_rows,
        "active_observations_in_six_complete_folds": int(
            (rows["anchor_index"] < fold_end).sum()
        ),
        "active_observations_in_training_remainder": int(
            (rows["anchor_index"] >= fold_end).sum()
        ),
        "positive_gross_folds": positive(fold_rows, "gross_slope"),
        "positive_adverse_folds": positive(fold_rows, "adverse_slope"),
        "years": year_rows,
        "positive_gross_years": positive(year_rows, "gross_slope"),
        "positive_adverse_years": positive(year_rows, "adverse_slope"),
    }


def descriptive(rows: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    x = rows["coherence"].to_numpy(float)
    gross = rows["gross_opportunity"].to_numpy(float)
    net = rows["net_payoff"].to_numpy(float)
    adverse = rows["adverse_excursion"].to_numpy(float)
    quantiles = np.quantile(x, [0, 0.25, 0.5, 0.75, 1])
    median = float(quantiles[2])
    low = rows[rows["coherence"] <= median]
    high = rows[rows["coherence"] > median]
    distribution = {
        "state_quantiles": dict(
            zip(("min", "q25", "median", "q75", "max"), quantiles, strict=True)
        ),
        "state_iqr": float(quantiles[3] - quantiles[1]),
        "gross_mean": float(gross.mean()),
        "gross_median": float(np.median(gross)),
        "gross_positive_weeks": int((gross > 0).sum()),
        "gross_zero_weeks": int((gross == 0).sum()),
        "net_mean": float(net.mean()),
        "net_median": float(np.median(net)),
        "net_positive_weeks": int((net > 0).sum()),
        "adverse_mean": float(adverse.mean()),
        "adverse_median": float(np.median(adverse)),
        "turnover_total": float(rows["turnover"].sum()),
        "fees_total": float(rows["fees"].sum()),
        "long_hours_total": int(rows["long_hours"].sum()),
        "mean_target_exposure": float(rows["long_hours"].sum() / (len(rows) * WEEK)),
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
    rng = np.random.default_rng(SEED)
    blocks = math.ceil(length / BLOCK)
    starts = rng.integers(0, length - BLOCK + 1, size=(RESAMPLES, blocks))
    return (starts[..., None] + np.arange(BLOCK)).reshape(RESAMPLES, -1)[:, :length]


def bootstrap_draws(table: pd.DataFrame, samples: np.ndarray) -> np.ndarray:
    draws = np.full((len(samples), 4), np.nan)
    for number, indices in enumerate(samples):
        rows = table.iloc[indices]
        rows = rows[rows["active_at_anchor"]]
        if len(rows) < 20 or np.std(rows["coherence"].to_numpy(float), ddof=1) <= 0:
            continue
        stats = target_statistics(rows)
        draws[number] = list(stats.values())
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
    names = tuple(point)
    ci95 = {
        name: np.quantile(draws[valid, column], [0.025, 0.975]).tolist()
        for column, name in enumerate(names)
    }
    distribution, median_split = descriptive(rows)
    temporal = breadth(rows)
    gates = {
        "gross_positive_lower_bound": point["gross_spearman"] > 0
        and ci95["gross_spearman"][0] > 0,
        "adverse_positive_lower_bound": point["adverse_spearman"] > 0
        and ci95["adverse_spearman"][0] > 0,
        "positive_economic_slopes": point["gross_slope_per_state_sd"] > 0
        and point["adverse_slope_per_state_sd"] > 0,
        "fold_breadth": temporal["positive_gross_folds"] >= 4
        and temporal["positive_adverse_folds"] >= 4,
        "year_breadth": temporal["positive_gross_years"] >= 2
        and temporal["positive_adverse_years"] >= 2,
        "state_dispersion": distribution["state_iqr"] >= 0.10,
        "median_partition_support": median_split["low_observations"] >= 20
        and median_split["high_observations"] >= 20,
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


def run(btc: Path, eth: Path) -> dict[str, Any]:
    btc_table, btc_metadata = build_table(btc, "BTC-USDT")
    eth_table, eth_metadata = build_table(eth, "ETH-USDT")
    if not np.array_equal(btc_table["anchor_index"], eth_table["anchor_index"]):
        raise ValueError("market weekly calendars diverged")
    samples = common_calendar_samples(len(btc_table))
    btc_result, btc_draws = summarize_market(btc_table, btc_metadata, samples)
    eth_result, eth_draws = summarize_market(eth_table, eth_metadata, samples)
    common_valid = np.all(np.isfinite(btc_draws), axis=1) & np.all(
        np.isfinite(eth_draws), axis=1
    )
    common_draws = np.median(
        np.stack([btc_draws[common_valid], eth_draws[common_valid]]), axis=0
    )
    common = {
        "valid_draws": int(common_valid.sum()),
        "valid_fraction": float(common_valid.mean()),
        "gross_spearman_point": float(
            np.median(
                [
                    btc_result["point"]["gross_spearman"],
                    eth_result["point"]["gross_spearman"],
                ]
            )
        ),
        "gross_spearman_ci95": np.quantile(common_draws[:, 0], [0.025, 0.975]).tolist(),
        "adverse_spearman_point": float(
            np.median(
                [
                    btc_result["point"]["adverse_spearman"],
                    eth_result["point"]["adverse_spearman"],
                ]
            )
        ),
        "adverse_spearman_ci95": np.quantile(
            common_draws[:, 1], [0.025, 0.975]
        ).tolist(),
        "gross_slope_point": float(
            np.median(
                [
                    btc_result["point"]["gross_slope_per_state_sd"],
                    eth_result["point"]["gross_slope_per_state_sd"],
                ]
            )
        ),
        "gross_slope_ci95": np.quantile(common_draws[:, 2], [0.025, 0.975]).tolist(),
        "adverse_slope_point": float(
            np.median(
                [
                    btc_result["point"]["adverse_slope_per_state_sd"],
                    eth_result["point"]["adverse_slope_per_state_sd"],
                ]
            )
        ),
        "adverse_slope_ci95": np.quantile(
            common_draws[:, 3], [0.025, 0.975]
        ).tolist(),
    }
    common_gate = (
        common["valid_fraction"] >= 0.95
        and common["gross_spearman_ci95"][0] > 0
        and common["adverse_spearman_ci95"][0] > 0
    )
    accepted = bool(
        btc_result["passes_market_gates"]
        and eth_result["passes_market_gates"]
        and common_gate
    )
    return {
        "family_id": "signed-path-coherence-opportunity-diagnostic-1h-v1",
        "issue": 803,
        "classification": "training-only architecture-eligibility diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "bar": "immutable public confirmed OKX SPOT 1H",
        "fee_one_way": FEE,
        "state": {
            "hours": WEEK,
            "formula": "log(close_t/close_t-168)/sum(abs(hourly_log_return),168H)",
            "conditioning": "carried daily 2160H B1 target is long at Monday anchor",
            "cadence": "completed Monday 00:00 UTC",
        },
        "sample": {
            "training": list(TRAIN),
            "parsed_rows_per_market": TRAIN[1],
            "frozen_prefix_rows": 43_441,
            "oos_values_parsed_or_accessed": False,
            "resamples": RESAMPLES,
            "block_calendar_weeks": BLOCK,
            "seed": SEED,
        },
        "markets": [btc_result, eth_result],
        "common_index": common,
        "common_index_gate": common_gate,
        "markets_passing": int(btc_result["passes_market_gates"])
        + int(eth_result["passes_market_gates"]),
        "accepted": accepted,
        "verdict": (
            "support_signed_path_coherence_opportunity_premise"
            if accepted
            else "reject_signed_path_coherence_opportunity_premise"
        ),
        "strategy_metrics": {
            "train": "not computed; candidate_count=0",
            "oos": "not accessed",
            "full": "not computed; candidate_count=0",
            "benchmark_comparison": "not applicable; diagnostic active-B1 target sleeves only",
            "maximum_drawdown": "not applicable to candidate; adverse excursion reported per target sleeve",
            "edge_per_turnover": "not applicable to candidate; target gross/net and turnover reported",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.btc_csv, args.eth_csv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
