"""Frozen strategy diagnostics, gates, and bilateral uncertainty."""

from __future__ import annotations

from typing import Any

import numpy as np
from common import ANNUAL_HOURS, FULL, OOS, TRAIN, finite_or_none
from metrics import (
    fold_year_diagnostics,
    metrics,
    paired_bootstrap,
    residual_sharpe,
    sampled_indices,
    sharpe_value,
)


def forecast_diagnostics(market: dict[str, Any], built: dict[str, Any]) -> dict[str, Any]:
    os, oe = OOS
    mask = built["decision_mask"].copy()
    index = np.arange(len(mask))
    mask &= (index >= os) & (index < oe)
    pred24 = built["predictions"][24]
    pred168 = built["predictions"][168]
    label24 = built["labels"][24]
    label168 = built["labels"][168]
    valid = mask & np.isfinite(pred24) & np.isfinite(pred168)
    groups: dict[str, Any] = {}
    sign_groups = {
        "both_positive": valid & (pred24 > 0) & (pred168 > 0),
        "short_only_positive": valid & (pred24 > 0) & (pred168 <= 0),
        "long_only_positive": valid & (pred24 <= 0) & (pred168 > 0),
        "both_nonpositive": valid & (pred24 <= 0) & (pred168 <= 0),
    }
    for name, group in sign_groups.items():
        groups[name] = {
            "count": int(np.sum(group)),
            "mean_realized_24h": finite_or_none(float(np.mean(label24[group])))
            if np.any(group)
            else None,
            "mean_realized_168h": finite_or_none(float(np.mean(label168[group])))
            if np.any(group)
            else None,
            "positive_realized_24h_fraction": float(np.mean(label24[group] > 0))
            if np.any(group)
            else None,
            "positive_realized_168h_fraction": float(np.mean(label168[group] > 0))
            if np.any(group)
            else None,
        }
    corr24 = valid & np.isfinite(label24)
    corr168 = valid & np.isfinite(label168)
    candidate = built["paths"]["candidate"]
    b1 = built["paths"]["B1"]
    cpos = candidate["position"][os:oe]
    bpos = b1["position"][os:oe]
    return {
        "oos_daily_decisions": int(np.sum(mask)),
        "oos_fitted_daily_decisions": int(np.sum(valid)),
        "forecast_sign_groups": groups,
        "forecast_realized_correlation_24h": finite_or_none(
            float(np.corrcoef(pred24[corr24], label24[corr24])[0, 1])
        ),
        "forecast_realized_correlation_168h": finite_or_none(
            float(np.corrcoef(pred168[corr168], label168[corr168])[0, 1])
        ),
        "median_training_rows_24h": float(np.median(built["training_rows"][24][valid])),
        "median_training_rows_168h": float(np.median(built["training_rows"][168][valid])),
        "candidate_only_hours": int(np.sum((cpos == 1) & (bpos == 0))),
        "b1_only_hours": int(np.sum((cpos == 0) & (bpos == 1))),
        "gross_timing_residual": float(np.sum(candidate["gross"][os:oe] - b1["gross"][os:oe])),
        "fee_residual": float(np.sum(candidate["fee"][os:oe] - b1["fee"][os:oe])),
        "net_arithmetic_residual": float(np.sum(candidate["net"][os:oe] - b1["net"][os:oe])),
    }


def evaluate_market(
    instrument: str,
    market: dict[str, Any],
    built: dict[str, Any],
    starts: np.ndarray,
) -> dict[str, Any]:
    paths = built["paths"]
    samples = {"train": TRAIN, "oos": OOS, "full": FULL}
    performance = {
        sample: {name: metrics(paths[name], *bounds) for name in ("candidate", "B0", "B1")}
        for sample, bounds in samples.items()
    }
    breadth = fold_year_diagnostics(paths["candidate"], market["timestamps"])
    os, oe = OOS
    candidate_oos = paths["candidate"]["net"][os:oe]
    b1_oos = paths["B1"]["net"][os:oe]
    bootstrap = paired_bootstrap(candidate_oos, b1_oos, starts)
    residual = residual_sharpe(candidate_oos, b1_oos)
    c = performance["oos"]["candidate"]
    b0 = performance["oos"]["B0"]
    b1 = performance["oos"]["B1"]
    concentration = breadth["positive_fold_concentration"]
    gates = {
        "positive_oos_return": c["net_return"] > 0,
        "positive_oos_sharpe": c["sharpe"] is not None and c["sharpe"] > 0,
        "return_at_least_B1": c["net_return"] >= b1["net_return"],
        "sharpe_at_least_B1": c["sharpe"] is not None
        and b1["sharpe"] is not None
        and c["sharpe"] >= b1["sharpe"],
        "drawdown_no_worse_B1": c["max_drawdown"] >= b1["max_drawdown"],
        "turnover_below_B0": c["turnover"] < b0["turnover"],
        "edge_per_turn_at_least_B1": c["edge_per_turn_bps"] is not None
        and b1["edge_per_turn_bps"] is not None
        and c["edge_per_turn_bps"] >= b1["edge_per_turn_bps"],
        "profitable_folds_at_least_7": breadth["profitable_folds"] >= 7,
        "profitable_years_at_least_3": breadth["profitable_years"] >= 3,
        "positive_fold_concentration_at_most_0_5": concentration is not None
        and concentration <= 0.5,
        "positive_residual_sharpe": residual is not None and residual > 0,
        "mean_delta_ci_lower_positive": bootstrap["annualized_mean_delta_ci95"][0] > 0,
        "sharpe_delta_ci_lower_positive": bootstrap["sharpe_delta_ci95"][0] > 0,
        "positive_full_return": performance["full"]["candidate"]["net_return"] > 0,
    }
    return {
        "instrument": instrument,
        "source": {
            "csv_path": market["csv_path"],
            "csv_sha256": market["csv_sha256"],
            "source_rows": market["source_rows"],
            "frozen_prefix_rows": 43_441,
            "frozen_start": market["timestamps"].iloc[0].isoformat(),
            "frozen_end": market["timestamps"].iloc[-1].isoformat(),
        },
        "performance": performance,
        "breadth": breadth,
        "residual_sharpe_vs_B1": residual,
        "bootstrap_vs_B1": bootstrap,
        "forecast_diagnostics": forecast_diagnostics(market, built),
        "gates": gates,
        "accepted": all(gates.values()),
    }


def common_bootstrap(
    markets: list[tuple[str, dict[str, Any]]], starts: np.ndarray
) -> dict[str, Any]:
    os, oe = OOS
    point_means: list[float] = []
    point_sharpes: list[float] = []
    for _, built in markets:
        c = built["paths"]["candidate"]["net"][os:oe]
        b = built["paths"]["B1"]["net"][os:oe]
        point_means.append(float(np.mean(c - b) * ANNUAL_HOURS))
        point_sharpes.append(sharpe_value(c) - sharpe_value(b))
    sampled_mean = np.empty(len(starts))
    sampled_sharpe = np.empty(len(starts))
    for k, block_starts in enumerate(starts):
        means: list[float] = []
        sharpes: list[float] = []
        for _, built in markets:
            c_all = built["paths"]["candidate"]["net"][os:oe]
            b_all = built["paths"]["B1"]["net"][os:oe]
            idx = sampled_indices(block_starts, len(c_all))
            c = c_all[idx]
            b = b_all[idx]
            means.append(float(np.mean(c - b) * ANNUAL_HOURS))
            sharpes.append(sharpe_value(c) - sharpe_value(b))
        sampled_mean[k] = float(np.median(means))
        sampled_sharpe[k] = float(np.median(sharpes))
    return {
        "market_aggregation": "median_of_independent_market_deltas",
        "annualized_mean_delta_point": float(np.median(point_means)),
        "annualized_mean_delta_ci95": [
            float(value) for value in np.quantile(sampled_mean, [0.025, 0.975])
        ],
        "sharpe_delta_point": finite_or_none(float(np.median(point_sharpes))),
        "sharpe_delta_ci95": [
            float(value) for value in np.nanquantile(sampled_sharpe, [0.025, 0.975])
        ],
    }
