#!/usr/bin/env python3
"""Reproduce issue #808's training-only B1 positive-regime stationarity diagnostic."""

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
    if len(frame) != TRAIN[1]:
        raise ValueError(f"{instrument} training-prefix row count changed")
    if not bool((frame["confirm"] == 1).all()):
        raise ValueError(f"{instrument} includes incomplete bars")
    if frame["timestamp"].iloc[0] != pd.Timestamp("2021-07-24T00:00:00Z"):
        raise ValueError(f"{instrument} source start changed")
    if not bool((frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all()):
        raise ValueError(f"{instrument} training prefix is not contiguous 1H")
    numeric = frame[["open", "close"]].to_numpy(float)
    if not np.isfinite(numeric).all() or not bool((numeric > 0).all()):
        raise ValueError(f"{instrument} has invalid prices")
    return frame, digest


def finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None


def corr(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 3 or np.std(x, ddof=1) <= 0 or np.std(y, ddof=1) <= 0:
        return float("nan")
    return float(np.corrcoef(x, y)[0, 1])


def assign_daily_regimes(
    endpoint: np.ndarray,
    daily_indices: np.ndarray,
) -> tuple[np.ndarray, dict[int, dict[str, int]]]:
    regime_for_index = np.full(len(endpoint), -1, dtype=np.int32)
    regimes: dict[int, dict[str, int]] = {}
    current = -1
    previous_active = False
    for index in daily_indices:
        active = bool(endpoint[index])
        if active and not previous_active:
            current += 1
            regimes[current] = {"full_start_index": int(index), "full_end_index": int(index)}
        if active:
            regime_for_index[index] = current
            regimes[current]["full_end_index"] = int(index)
        previous_active = active
    return regime_for_index, regimes


def build_labels(
    path: Path,
    instrument: str,
) -> tuple[pd.DataFrame, dict[int, dict[str, int]], dict[str, Any]]:
    frame, digest = load(path, instrument)
    times = frame["timestamp"]
    opens = frame["open"].to_numpy(float)
    close = frame["close"].to_numpy(float)
    indices = np.arange(len(frame))

    endpoint = np.zeros(len(frame), dtype=np.int8)
    endpoint[TREND:] = close[TREND:] > close[:-TREND]
    daily_indices = indices[(times.dt.hour.to_numpy() == 0) & (indices >= TREND)]
    regime_for_index, all_regimes = assign_daily_regimes(endpoint, daily_indices)

    calendar_anchors = indices[
        (times.dt.hour.to_numpy() == 0) & (indices >= TRAIN[0]) & (indices + 25 < TRAIN[1])
    ]
    if not np.all(np.diff(calendar_anchors) == DAY):
        raise ValueError("eligible daily calendar changed")

    rows: list[dict[str, Any]] = []
    for anchor in calendar_anchors:
        if not endpoint[anchor]:
            continue
        regime_id = int(regime_for_index[anchor])
        if regime_id < 0:
            raise ValueError("active anchor lacks a causal regime")
        decisions = np.arange(anchor, anchor + DAY)
        hourly = opens[decisions + 2] / opens[decisions + 1] - 1
        gross = float(hourly.sum())
        rows.append(
            {
                "anchor_index": int(anchor),
                "anchor_timestamp": times.iloc[anchor].isoformat(),
                "regime_id": regime_id,
                "gross_opportunity": gross,
                "net_payoff": gross - 2 * FEE,
                "adverse_excursion": float(np.r_[0.0, np.cumsum(hourly)].min()),
                "turnover": 2.0,
                "fees": 2 * FEE,
            }
        )

    table = pd.DataFrame(rows)
    if table.empty:
        raise ValueError(f"{instrument} has no active training labels")
    return table, all_regimes, {
        "instrument": instrument,
        "artifact_id": ARTIFACTS[instrument],
        "csv_sha256": digest,
        "parsed_rows": len(frame),
        "calendar_anchors": len(calendar_anchors),
        "active_anchors": len(table),
        "first_anchor": table["anchor_timestamp"].iloc[0],
        "last_anchor": table["anchor_timestamp"].iloc[-1],
    }


def regime_table(
    labels: pd.DataFrame,
    all_regimes: dict[int, dict[str, int]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for regime_id, part in labels.groupby("regime_id", sort=True):
        info = all_regimes[int(regime_id)]
        gross = part["gross_opportunity"].to_numpy(float)
        net = part["net_payoff"].to_numpy(float)
        adverse = part["adverse_excursion"].to_numpy(float)
        scored_last = int(part["anchor_index"].iloc[-1])
        rows.append(
            {
                "regime_id": int(regime_id),
                "first_scored_anchor": part["anchor_timestamp"].iloc[0],
                "last_scored_anchor": part["anchor_timestamp"].iloc[-1],
                "full_start_index": info["full_start_index"],
                "full_end_index": info["full_end_index"],
                "left_censored": bool(info["full_start_index"] < TRAIN[0]),
                "right_censored": bool(info["full_end_index"] > scored_last),
                "scored_days": len(part),
                "mean_gross": float(gross.mean()),
                "median_gross": float(np.median(gross)),
                "cumulative_gross": float(gross.sum()),
                "mean_net": float(net.mean()),
                "median_net": float(np.median(net)),
                "cumulative_net": float(net.sum()),
                "mean_adverse": float(adverse.mean()),
                "gross_positive_fraction": float((gross > 0).mean()),
                "net_positive_fraction": float((net > 0).mean()),
                "lag1_gross_correlation": (
                    finite_or_none(corr(gross[:-1], gross[1:])) if len(gross) >= 4 else None
                ),
            }
        )
    regimes = pd.DataFrame(rows)
    abs_total = float(np.abs(regimes["cumulative_gross"]).sum())
    positive_total = float(regimes["cumulative_gross"].clip(lower=0).sum())
    regimes["absolute_gross_contribution_share"] = (
        np.abs(regimes["cumulative_gross"]) / abs_total if abs_total > 0 else 0.0
    )
    regimes["positive_gross_contribution_share"] = (
        regimes["cumulative_gross"].clip(lower=0) / positive_total if positive_total > 0 else 0.0
    )
    return regimes


def pooled_within_regime_lag1(labels: pd.DataFrame) -> float:
    left: list[np.ndarray] = []
    right: list[np.ndarray] = []
    for _, part in labels.groupby("regime_id", sort=True):
        values = part["gross_opportunity"].to_numpy(float)
        if len(values) < 2:
            continue
        centered = values - values.mean()
        left.append(centered[:-1])
        right.append(centered[1:])
    if not left:
        return float("nan")
    return corr(np.concatenate(left), np.concatenate(right))


def leave_one_out(regimes: pd.DataFrame, labels: pd.DataFrame) -> dict[str, Any]:
    equal_rows: list[dict[str, Any]] = []
    day_rows: list[dict[str, Any]] = []
    for regime_id in regimes["regime_id"].astype(int):
        remaining_regimes = regimes[regimes["regime_id"] != regime_id]
        remaining_days = labels[labels["regime_id"] != regime_id]
        equal_rows.append(
            {
                "omitted_regime": regime_id,
                "gross": float(remaining_regimes["mean_gross"].mean()),
                "net": float(remaining_regimes["mean_net"].mean()),
            }
        )
        day_rows.append(
            {
                "omitted_regime": regime_id,
                "gross": float(remaining_days["gross_opportunity"].mean()),
                "net": float(remaining_days["net_payoff"].mean()),
            }
        )

    def minimum(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
        item = min(rows, key=lambda row: row[key])
        return {"value": item[key], "omitted_regime": item["omitted_regime"]}

    return {
        "equal_regime_weight": {
            "minimum_gross": minimum(equal_rows, "gross"),
            "minimum_net": minimum(equal_rows, "net"),
            "all": equal_rows,
        },
        "day_weight": {
            "minimum_gross": minimum(day_rows, "gross"),
            "minimum_net": minimum(day_rows, "net"),
            "all": day_rows,
        },
    }


def temporal_breadth(labels: pd.DataFrame) -> dict[str, Any]:
    folds: list[dict[str, Any]] = []
    for number in range(6):
        start = TRAIN[0] + number * TREND
        part = labels[(labels["anchor_index"] >= start) & (labels["anchor_index"] < start + TREND)]
        folds.append(
            {
                "fold": number + 1,
                "start_index": start,
                "end_index_exclusive": start + TREND,
                "observations": len(part),
                "mean_gross": float(part["gross_opportunity"].mean()) if len(part) else None,
                "mean_net": float(part["net_payoff"].mean()) if len(part) else None,
            }
        )
    years = pd.to_datetime(labels["anchor_timestamp"], utc=True).dt.year
    year_rows: list[dict[str, Any]] = []
    for year in sorted(years.unique()):
        part = labels[years == year]
        year_rows.append(
            {
                "year": int(year),
                "observations": len(part),
                "mean_gross": float(part["gross_opportunity"].mean()),
                "mean_net": float(part["net_payoff"].mean()),
            }
        )

    def positive(items: list[dict[str, Any]], key: str) -> int:
        return sum(item[key] is not None and item[key] > 0 for item in items)

    return {
        "folds": folds,
        "positive_gross_folds": positive(folds, "mean_gross"),
        "positive_net_folds": positive(folds, "mean_net"),
        "years": year_rows,
        "positive_gross_years": positive(year_rows, "mean_gross"),
        "positive_net_years": positive(year_rows, "mean_net"),
    }


def bootstrap(regimes: pd.DataFrame) -> tuple[dict[str, Any], np.ndarray]:
    n_regimes = len(regimes)
    generator = np.random.default_rng(SEED)
    samples = generator.integers(0, n_regimes, size=(RESAMPLES, n_regimes))
    means_gross = regimes["mean_gross"].to_numpy(float)
    means_net = regimes["mean_net"].to_numpy(float)
    sums_gross = regimes["cumulative_gross"].to_numpy(float)
    sums_net = regimes["cumulative_net"].to_numpy(float)
    durations = regimes["scored_days"].to_numpy(float)
    draws = np.full((RESAMPLES, 7), np.nan)
    for number, sample in enumerate(samples):
        selected_gross_mean = means_gross[sample]
        selected_net_mean = means_net[sample]
        selected_gross_sum = sums_gross[sample]
        selected_net_sum = sums_net[sample]
        selected_duration = durations[sample]
        denom = selected_duration.sum()
        abs_denom = np.abs(selected_gross_sum).sum()
        if denom <= 0:
            continue
        draws[number] = (
            selected_gross_mean.mean(),
            selected_net_mean.mean(),
            np.median(selected_gross_mean),
            np.median(selected_net_mean),
            selected_gross_sum.sum() / denom,
            selected_net_sum.sum() / denom,
            np.abs(selected_gross_sum).max() / abs_denom if abs_denom > 0 else 0.0,
        )
    valid = np.all(np.isfinite(draws), axis=1)
    names = (
        "equal_weight_mean_gross",
        "equal_weight_mean_net",
        "median_regime_mean_gross",
        "median_regime_mean_net",
        "day_weight_mean_gross",
        "day_weight_mean_net",
        "max_absolute_gross_contribution_share",
    )
    summary: dict[str, Any] = {
        "resamples": RESAMPLES,
        "seed": SEED,
        "valid_draws": int(valid.sum()),
        "valid_fraction": float(valid.mean()),
    }
    for column, name in enumerate(names):
        summary[f"{name}_ci95"] = np.quantile(draws[valid, column], [0.025, 0.975]).tolist()
    breadth_gross = np.empty(RESAMPLES)
    breadth_net = np.empty(RESAMPLES)
    for number, sample in enumerate(samples):
        breadth_gross[number] = (means_gross[sample] > 0).mean()
        breadth_net[number] = (means_net[sample] > 0).mean()
    summary["positive_gross_regime_fraction_ci95"] = np.quantile(
        breadth_gross, [0.025, 0.975]
    ).tolist()
    summary["positive_net_regime_fraction_ci95"] = np.quantile(breadth_net, [0.025, 0.975]).tolist()
    return summary, draws


def summarize_market(
    labels: pd.DataFrame,
    regimes: pd.DataFrame,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    durations = regimes["scored_days"].to_numpy(float)
    mean_gross = regimes["mean_gross"].to_numpy(float)
    mean_net = regimes["mean_net"].to_numpy(float)
    mean_adverse = regimes["mean_adverse"].to_numpy(float)
    loo = leave_one_out(regimes, labels)
    breadth = temporal_breadth(labels)
    uncertainty, _ = bootstrap(regimes)
    per_regime_lag = regimes["lag1_gross_correlation"].dropna().to_numpy(float)
    required_years = math.ceil(2 * len(breadth["years"]) / 3)

    max_abs_share = float(regimes["absolute_gross_contribution_share"].max())
    max_pos_share = float(regimes["positive_gross_contribution_share"].max())
    equal_gross = float(mean_gross.mean())
    equal_net = float(mean_net.mean())
    day_gross = float(labels["gross_opportunity"].mean())
    day_net = float(labels["net_payoff"].mean())
    median_gross = float(np.median(mean_gross))
    median_net = float(np.median(mean_net))
    positive_gross_count = int((mean_gross > 0).sum())
    positive_net_count = int((mean_net > 0).sum())

    gates = {
        "positive_median_regime_payoff": median_gross > 0 and median_net > 0,
        "profitable_regime_breadth": positive_gross_count > len(regimes) / 2
        and positive_net_count >= len(regimes) / 2,
        "equal_weight_positive_lower_bounds": equal_gross > 0
        and equal_net > 0
        and uncertainty["equal_weight_mean_gross_ci95"][0] > 0
        and uncertainty["equal_weight_mean_net_ci95"][0] > 0,
        "day_weight_positive_lower_bounds": day_gross > 0
        and day_net > 0
        and uncertainty["day_weight_mean_gross_ci95"][0] > 0
        and uncertainty["day_weight_mean_net_ci95"][0] > 0,
        "leave_one_out_equal_weight": loo["equal_regime_weight"]["minimum_gross"]["value"] > 0
        and loo["equal_regime_weight"]["minimum_net"]["value"] > 0,
        "leave_one_out_day_weight": loo["day_weight"]["minimum_gross"]["value"] > 0
        and loo["day_weight"]["minimum_net"]["value"] > 0,
        "non_dominance": max_abs_share <= 0.35 and max_pos_share <= 0.50,
        "fold_breadth": breadth["positive_gross_folds"] >= 4
        and breadth["positive_net_folds"] >= 4,
        "year_breadth": breadth["positive_gross_years"] >= required_years
        and breadth["positive_net_years"] >= required_years,
        "valid_cluster_bootstrap": uncertainty["valid_fraction"] >= 0.95,
    }

    return {
        **metadata,
        "regime_count": len(regimes),
        "left_censored_regimes": int(regimes["left_censored"].sum()),
        "right_censored_regimes": int(regimes["right_censored"].sum()),
        "duration_quantiles_days": dict(
            zip(
                ("min", "q25", "median", "q75", "max"),
                np.quantile(durations, [0, 0.25, 0.5, 0.75, 1]).tolist(),
                strict=True,
            )
        ),
        "regime_breadth": {
            "positive_mean_gross_count": positive_gross_count,
            "positive_mean_net_count": positive_net_count,
            "positive_mean_gross_fraction": float(positive_gross_count / len(regimes)),
            "positive_mean_net_fraction": float(positive_net_count / len(regimes)),
        },
        "regime_balanced": {
            "median_mean_gross": median_gross,
            "median_mean_net": median_net,
            "median_mean_adverse": float(np.median(mean_adverse)),
            "equal_weight_mean_gross": equal_gross,
            "equal_weight_mean_net": equal_net,
            "equal_weight_mean_adverse": float(mean_adverse.mean()),
        },
        "day_weight": {
            "mean_gross": day_gross,
            "mean_net": day_net,
            "mean_adverse": float(labels["adverse_excursion"].mean()),
            "median_gross": float(labels["gross_opportunity"].median()),
            "median_net": float(labels["net_payoff"].median()),
            "gross_positive_days": int((labels["gross_opportunity"] > 0).sum()),
            "net_positive_days": int((labels["net_payoff"] > 0).sum()),
            "turnover_total": float(labels["turnover"].sum()),
            "fees_total": float(labels["fees"].sum()),
        },
        "concentration": {
            "max_absolute_gross_contribution_share": max_abs_share,
            "max_positive_gross_contribution_share": max_pos_share,
            "dominant_absolute_regime": int(
                regimes.loc[regimes["absolute_gross_contribution_share"].idxmax(), "regime_id"]
            ),
            "dominant_positive_regime": int(
                regimes.loc[regimes["positive_gross_contribution_share"].idxmax(), "regime_id"]
            ),
        },
        "leave_one_regime_out": loo,
        "within_regime_dependence": {
            "pooled_centered_lag1_gross_correlation": finite_or_none(
                pooled_within_regime_lag1(labels)
            ),
            "eligible_per_regime_correlations": len(per_regime_lag),
            "median_per_regime_lag1_gross_correlation": (
                float(np.median(per_regime_lag)) if len(per_regime_lag) else None
            ),
        },
        "temporal_breadth": breadth,
        "uncertainty": uncertainty,
        "gates": gates,
        "passes_market_gates": bool(all(gates.values())),
        "regimes": regimes.to_dict(orient="records"),
    }


def run(btc_path: Path, eth_path: Path) -> dict[str, Any]:
    btc_labels, btc_all_regimes, btc_meta = build_labels(btc_path, "BTC-USDT")
    eth_labels, eth_all_regimes, eth_meta = build_labels(eth_path, "ETH-USDT")
    btc_regimes = regime_table(btc_labels, btc_all_regimes)
    eth_regimes = regime_table(eth_labels, eth_all_regimes)
    btc = summarize_market(btc_labels, btc_regimes, btc_meta)
    eth = summarize_market(eth_labels, eth_regimes, eth_meta)
    accepted = btc["passes_market_gates"] and eth["passes_market_gates"]
    return {
        "family_id": "positive-regime-opportunity-stationarity-closure-1h-v1",
        "issue": 808,
        "classification": "training-only architecture-eligibility closure diagnostic",
        "candidate_count": 0,
        "diagnostic_count": 1,
        "parameter_grid_count": 0,
        "bar": "immutable public confirmed OKX SPOT 1H",
        "fee_one_way": FEE,
        "training_indices": list(TRAIN),
        "oos_accessed": False,
        "markets": [btc, eth],
        "markets_passing": int(btc["passes_market_gates"]) + int(eth["passes_market_gates"]),
        "accepted": bool(accepted),
        "verdict": (
            "support_positive_regime_opportunity_stationarity_premise"
            if accepted
            else "reject_positive_regime_opportunity_stationarity_premise"
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc", type=Path, required=True)
    parser.add_argument("--eth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.btc, args.eth)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"accepted": result["accepted"], "verdict": result["verdict"]}))


if __name__ == "__main__":
    main()
