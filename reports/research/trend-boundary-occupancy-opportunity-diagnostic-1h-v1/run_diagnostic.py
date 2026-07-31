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
TRAIN = (2_880, 17_520)
TREND = 2_160
WEEK = 168
BOUNDARY = 0.25
RESAMPLES = 5_000
BLOCK = 4
SEED = 20_260_731
EXPECTED = {
    "BTC-USDT": "40c7ba3dbf64b8b31c634a79e1a2d5e2fa9d60b024c1fd62848d37ed967c13a0",
    "ETH-USDT": "0164a5cc1730f70ad9817980d67d6350cf71013cdb759c1a153a66890127d6f8",
}
ARTIFACT = {"BTC-USDT": 8769605568, "ETH-USDT": 8769619607}


def load(path: Path, instrument: str) -> tuple[pd.DataFrame, str]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != EXPECTED[instrument]:
        raise ValueError(f"{instrument} immutable CSV hash mismatch")
    frame = pd.read_csv(path, nrows=TRAIN[1], parse_dates=["timestamp"])
    if len(frame) != TRAIN[1] or not bool((frame["confirm"] == 1).all()):
        raise ValueError(f"{instrument} training-prefix contract failed")
    if frame["timestamp"].iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError("source start changed")
    if not bool((frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all()):
        raise ValueError(f"{instrument} training prefix is not contiguous 1H")
    return frame, digest


def b1(times: pd.Series, close: np.ndarray) -> np.ndarray:
    endpoint = np.zeros(len(close), dtype=np.int8)
    endpoint[TREND:] = close[TREND:] > close[:-TREND]
    position = np.zeros(len(close), dtype=np.int8)
    held = 0
    for index in range(TREND, len(close)):
        if times.iloc[index].hour == 0:
            held = int(endpoint[index])
        position[index] = held
    return position


def build_table(path: Path, instrument: str) -> tuple[pd.DataFrame, dict[str, object]]:
    frame, digest = load(path, instrument)
    times = frame["timestamp"]
    opens = frame["open"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    log_close = np.log(close)
    returns = np.r_[np.nan, np.diff(log_close)]
    position = b1(times, close)
    index = np.arange(len(frame))
    anchors = index[
        (times.dt.dayofweek.to_numpy() == 0)
        & (times.dt.hour.to_numpy() == 0)
        & (index - 167 >= TRAIN[0])
        & (index + 169 < TRAIN[1])
    ]
    if len(anchors) != 85 or not np.all(np.diff(anchors) == WEEK):
        raise ValueError("eligible anchor contract changed")

    rows = []
    for anchor in anchors:
        state = np.arange(anchor - 167, anchor + 1)
        rv = np.sqrt(np.array([np.mean(returns[i - 167 : i + 1] ** 2) for i in state], dtype=float))
        if not np.all(np.isfinite(rv)) or np.any(rv <= 0):
            raise ValueError("undefined realised volatility")
        distance = np.abs(log_close[state] - log_close[state - TREND]) / (math.sqrt(TREND) * rv)
        occupancy = float(np.mean(distance <= BOUNDARY))
        decisions = np.arange(anchor, anchor + WEEK)
        held = position[decisions].astype(float)
        hourly = held * (opens[decisions + 2] / opens[decisions + 1] - 1)
        turnover = float(held[0] + np.abs(np.diff(held)).sum() + held[-1])
        rows.append(
            {
                "anchor_index": int(anchor),
                "anchor_timestamp": times.iloc[anchor].isoformat(),
                "occupancy": occupancy,
                "clearance": 1 - occupancy,
                "gross_opportunity": float(hourly.sum()),
                "net_payoff": float(hourly.sum() - FEE * turnover),
                "turnover": turnover,
                "fees": FEE * turnover,
                "adverse_excursion": float(np.r_[0, np.cumsum(hourly)].min()),
                "near_boundary_hours": int(np.sum(distance <= BOUNDARY)),
                "long_hours": int(held.sum()),
            }
        )
    table = pd.DataFrame(rows)
    return table, {
        "instrument": instrument,
        "artifact_id": ARTIFACT[instrument],
        "csv_sha256": digest,
        "eligible_anchors": len(table),
        "first_anchor": table["anchor_timestamp"].iloc[0],
        "last_anchor": table["anchor_timestamp"].iloc[-1],
    }


def rho(x: np.ndarray, y: np.ndarray) -> float:
    rx = pd.Series(x).rank(method="average").to_numpy(float)
    ry = pd.Series(y).rank(method="average").to_numpy(float)
    if len(x) < 3 or np.std(rx, ddof=1) <= 0 or np.std(ry, ddof=1) <= 0:
        raise ValueError("undefined Spearman statistic")
    return float(np.corrcoef(rx, ry)[0, 1])


def slope(x: np.ndarray, y: np.ndarray) -> float:
    scale = float(np.std(x, ddof=1))
    if len(x) < 3 or scale <= 0:
        raise ValueError("undefined standardized slope")
    z = (x - np.mean(x)) / scale
    return float(np.linalg.lstsq(np.c_[np.ones(len(z)), z], y, rcond=None)[0][1])


def statistics(table: pd.DataFrame) -> dict[str, float]:
    x = table["clearance"].to_numpy(float)
    gross = table["gross_opportunity"].to_numpy(float)
    adverse = table["adverse_excursion"].to_numpy(float)
    return {
        "gross_spearman": rho(x, gross),
        "adverse_spearman": rho(x, adverse),
        "gross_slope_per_sd_clearance": slope(x, gross),
        "adverse_slope_per_sd_clearance": slope(x, adverse),
    }


def breadth(table: pd.DataFrame) -> dict[str, object]:
    x = table["clearance"].to_numpy(float)
    gross = table["gross_opportunity"].to_numpy(float)
    adverse = table["adverse_excursion"].to_numpy(float)
    anchors = table["anchor_index"].to_numpy(int)
    years = pd.to_datetime(table["anchor_timestamp"], utc=True).dt.year.to_numpy()

    def row(mask: np.ndarray, label: dict[str, int]) -> dict[str, object]:
        enough = int(mask.sum()) >= 4 and np.std(x[mask], ddof=1) > 0
        return {
            **label,
            "observations": int(mask.sum()),
            "gross_slope": slope(x[mask], gross[mask]) if enough else None,
            "adverse_slope": slope(x[mask], adverse[mask]) if enough else None,
        }

    folds = []
    for number in range(6):
        start = TRAIN[0] + number * TREND
        mask = (anchors >= start) & (anchors < start + TREND)
        folds.append(
            row(
                mask,
                {"fold": number + 1, "start_index": start, "end_index_exclusive": start + TREND},
            )
        )
    year_rows = [row(years == year, {"year": year}) for year in (2021, 2022, 2023)]

    def positive(rows, key):
        return sum(item[key] is not None and item[key] > 0 for item in rows)

    return {
        "folds": folds,
        "positive_gross_folds": positive(folds, "gross_slope"),
        "positive_adverse_folds": positive(folds, "adverse_slope"),
        "years": year_rows,
        "positive_gross_years": positive(year_rows, "gross_slope"),
        "positive_adverse_years": positive(year_rows, "adverse_slope"),
    }


def state_summary(table: pd.DataFrame) -> tuple[dict[str, object], dict[str, object]]:
    occupancy = table["occupancy"].to_numpy(float)
    gross = table["gross_opportunity"].to_numpy(float)
    net = table["net_payoff"].to_numpy(float)
    adverse = table["adverse_excursion"].to_numpy(float)
    q = np.quantile(occupancy, [0, 0.25, 0.5, 0.75, 1])
    distribution = {
        "occupancy_quantiles": dict(zip(("min", "q25", "median", "q75", "max"), q, strict=True)),
        "occupancy_iqr": float(q[3] - q[1]),
        "clearance_mean": float(table["clearance"].mean()),
        "gross_mean": float(gross.mean()),
        "gross_median": float(np.median(gross)),
        "gross_positive_weeks": int(np.sum(gross > 0)),
        "zero_gross_weeks": int(np.sum(gross == 0)),
        "net_mean": float(net.mean()),
        "net_median": float(np.median(net)),
        "net_positive_weeks": int(np.sum(net > 0)),
        "adverse_mean": float(adverse.mean()),
        "adverse_median": float(np.median(adverse)),
        "turnover_total": float(table["turnover"].sum()),
        "fees_total": float(table["fees"].sum()),
        "long_hours_total": int(table["long_hours"].sum()),
        "inactive_target_weeks": int(np.sum(table["long_hours"] == 0)),
        "zero_occupancy_weeks": int(np.sum(occupancy == 0)),
        "max_absolute_gross_share": float(np.abs(gross).max() / np.abs(gross).sum()),
        "max_absolute_net_share": float(np.abs(net).max() / np.abs(net).sum()),
    }
    median = float(table["clearance"].median())
    low = table["clearance"] < median
    high = table["clearance"] > median

    def means(mask: pd.Series) -> dict[str, float | int | None]:
        if not bool(mask.any()):
            return {"observations": 0, "gross_mean": None, "adverse_mean": None, "net_mean": None}
        return {
            "observations": int(mask.sum()),
            "gross_mean": float(table.loc[mask, "gross_opportunity"].mean()),
            "adverse_mean": float(table.loc[mask, "adverse_excursion"].mean()),
            "net_mean": float(table.loc[mask, "net_payoff"].mean()),
        }

    lo, hi = means(low), means(high)
    split = {
        "clearance_median": median,
        "low_clearance": lo,
        "high_clearance": hi,
        "median_ties": int(np.sum(table["clearance"] == median)),
        "high_minus_low_gross": None if not high.any() else hi["gross_mean"] - lo["gross_mean"],
        "high_minus_low_adverse": (
            None if not high.any() else hi["adverse_mean"] - lo["adverse_mean"]
        ),
        "high_minus_low_net": None if not high.any() else hi["net_mean"] - lo["net_mean"],
    }
    return distribution, split


def diagnostics(table: pd.DataFrame) -> dict[str, object]:
    active = table["long_hours"].to_numpy(int) > 0
    result = {
        "active_target_weeks": int(active.sum()),
        "inactive_target_weeks": int((~active).sum()),
        "zero_occupancy_weeks": int(np.sum(table["occupancy"] == 0)),
        "active_and_positive_occupancy_weeks": int(np.sum(active & (table["occupancy"] > 0))),
        "active_gross_mean": float(table.loc[active, "gross_opportunity"].mean()),
        "inactive_gross_mean": float(table.loc[~active, "gross_opportunity"].mean()),
    }
    result["active_only_gross_spearman"] = rho(
        table.loc[active, "clearance"].to_numpy(float),
        table.loc[active, "gross_opportunity"].to_numpy(float),
    )
    result["active_only_adverse_spearman"] = rho(
        table.loc[active, "clearance"].to_numpy(float),
        table.loc[active, "adverse_excursion"].to_numpy(float),
    )
    return result


def sample_indices(n: int) -> np.ndarray:
    rng = np.random.default_rng(SEED)
    starts = rng.integers(0, n - BLOCK + 1, size=(RESAMPLES, math.ceil(n / BLOCK)))
    return (starts[..., None] + np.arange(BLOCK)).reshape(RESAMPLES, -1)[:, :n]


def summarize(table: pd.DataFrame, meta: dict[str, object], sampled: np.ndarray):
    point = statistics(table)
    x = table["clearance"].to_numpy(float)
    gross = table["gross_opportunity"].to_numpy(float)
    adverse = table["adverse_excursion"].to_numpy(float)
    draws = np.array(
        [
            [
                rho(x[i], gross[i]),
                rho(x[i], adverse[i]),
                slope(x[i], gross[i]),
                slope(x[i], adverse[i]),
            ]
            for i in sampled
        ]
    )
    names = tuple(point)
    ci = {name: np.quantile(draws[:, j], [0.025, 0.975]).tolist() for j, name in enumerate(names)}
    broad = breadth(table)
    distribution, split = state_summary(table)
    accepted = (
        point["gross_spearman"] > 0
        and ci["gross_spearman"][0] > 0
        and point["adverse_spearman"] > 0
        and ci["adverse_spearman"][0] > 0
        and broad["positive_gross_folds"] >= 4
        and broad["positive_adverse_folds"] >= 4
        and broad["positive_gross_years"] >= 2
        and broad["positive_adverse_years"] >= 2
        and distribution["occupancy_iqr"] >= 0.10
        and split["low_clearance"]["observations"] >= 20
        and split["high_clearance"]["observations"] >= 20
        and split["high_minus_low_gross"] is not None
        and split["high_minus_low_gross"] > 0
        and split["high_minus_low_adverse"] is not None
        and split["high_minus_low_adverse"] > 0
    )
    return {
        **meta,
        "point": point,
        "ci95": ci,
        "breadth": broad,
        "distribution": distribution,
        "median_split": split,
        "failure_diagnostic": diagnostics(table),
        "accepted": bool(accepted),
    }, draws


def run(btc: Path, eth: Path) -> dict[str, object]:
    btc_table, btc_meta = build_table(btc, "BTC-USDT")
    eth_table, eth_meta = build_table(eth, "ETH-USDT")
    if not np.array_equal(btc_table["anchor_index"], eth_table["anchor_index"]):
        raise ValueError("market anchor calendars diverged")
    sampled = sample_indices(85)
    btc_result, btc_draws = summarize(btc_table, btc_meta, sampled)
    eth_result, eth_draws = summarize(eth_table, eth_meta, sampled)
    names = tuple(btc_result["point"])
    common_draws = np.median(np.stack([btc_draws, eth_draws]), axis=0)
    common = {
        "point": {
            name: float(np.median([btc_result["point"][name], eth_result["point"][name]]))
            for name in names
        },
        "ci95": {
            name: np.quantile(common_draws[:, j], [0.025, 0.975]).tolist()
            for j, name in enumerate(names)
        },
    }
    accepted = bool(btc_result["accepted"] and eth_result["accepted"])
    return {
        "family_id": "trend-boundary-occupancy-opportunity-diagnostic-1h-v1",
        "issue": 798,
        "classification": "training-only architecture-eligibility diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "bar": "public confirmed OKX SPOT 1H",
        "fee_one_way": FEE,
        "state": {
            "trend_hours": TREND,
            "occupancy_hours": WEEK,
            "boundary": BOUNDARY,
            "scaled_distance": "abs(log(close_t/close_t-2160))/(sqrt(2160)*RMS168(log return))",
            "cadence": "completed Monday 00:00 UTC",
        },
        "sample": {
            "training": list(TRAIN),
            "frozen_prefix_rows": 43_441,
            "parsed_rows_per_market": TRAIN[1],
            "oos_values_parsed_or_accessed": False,
            "oos_accessed_for_statistics": False,
            "resamples": RESAMPLES,
            "block_weeks": BLOCK,
            "seed": SEED,
        },
        "markets": [btc_result, eth_result],
        "common_index": common,
        "markets_passing": int(btc_result["accepted"]) + int(eth_result["accepted"]),
        "accepted": accepted,
        "verdict": (
            "support_trend_boundary_occupancy_opportunity_premise"
            if accepted
            else "reject_trend_boundary_occupancy_opportunity_premise"
        ),
        "strategy_metrics": {
            "train": "not computed; candidate_count=0",
            "oos": "not accessed",
            "full": "not computed; candidate_count=0",
            "benchmark_comparison": "not applicable; diagnostic labels only",
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
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
