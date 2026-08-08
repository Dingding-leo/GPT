from __future__ import annotations

import math

import numpy as np
import pandas as pd

BOOTSTRAP_DRAWS = 5_000
BOOTSTRAP_BLOCK = 7
BOOTSTRAP_SEEDS = {"BTCUSDT": 202608091143, "ETHUSDT": 202608091144}


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx = pd.Series(x).rank(method="average").to_numpy(float)
    ry = pd.Series(y).rank(method="average").to_numpy(float)
    if np.std(rx) == 0 or np.std(ry) == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def std_slope(x: np.ndarray, y: np.ndarray) -> float:
    sd = float(np.std(x, ddof=0))
    if not math.isfinite(sd) or sd <= 0:
        return float("nan")
    z = (x - float(np.mean(x))) / sd
    centered = z - np.mean(z)
    denominator = float(np.dot(centered, centered))
    if denominator <= 0:
        return float("nan")
    return float(np.dot(centered, y - np.mean(y)) / denominator)


def tercile_effect(x: np.ndarray, y: np.ndarray) -> float:
    order = np.argsort(x, kind="mergesort")
    k = len(order) // 3
    if k < 1:
        return float("nan")
    return float(np.mean(y[order[-k:]]) - np.mean(y[order[:k]]))


def triple(x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    return {
        "rho": spearman(x, y),
        "slope": std_slope(x, y),
        "tercile": tercile_effect(x, y),
    }


def bootstrap_intervals(
    symbol: str,
    x: np.ndarray,
    net: np.ndarray,
    adverse: np.ndarray,
) -> dict[str, list[float]]:
    n = len(x)
    starts = np.arange(0, n - BOOTSTRAP_BLOCK + 1)
    if len(starts) < 1:
        raise ValueError("not enough opportunities for bootstrap")
    rng = np.random.default_rng(BOOTSTRAP_SEEDS[symbol])
    draws = {"net_rho": [], "net_slope": [], "adverse_rho": [], "adverse_slope": []}
    blocks_needed = math.ceil(n / BOOTSTRAP_BLOCK)
    for _ in range(BOOTSTRAP_DRAWS):
        picked: list[int] = []
        for start in rng.choice(starts, size=blocks_needed, replace=True):
            picked.extend(range(int(start), int(start) + BOOTSTRAP_BLOCK))
        index = np.asarray(picked[:n], dtype=int)
        draws["net_rho"].append(spearman(x[index], net[index]))
        draws["net_slope"].append(std_slope(x[index], net[index]))
        draws["adverse_rho"].append(spearman(x[index], adverse[index]))
        draws["adverse_slope"].append(std_slope(x[index], adverse[index]))
    return {
        key: [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]
        for key, values in draws.items()
    }


def fold_stats(frame: pd.DataFrame) -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for fold, index in enumerate(np.array_split(np.arange(len(frame)), 4), 1):
        sub = frame.iloc[index]
        x = sub["feature"].to_numpy(float)
        output.append(
            {
                "fold": fold,
                "rows": len(sub),
                "start": sub["timestamp"].iloc[0],
                "end": sub["timestamp"].iloc[-1],
                "net_slope": std_slope(x, sub["net"].to_numpy(float)),
                "adverse_slope": std_slope(x, sub["adverse"].to_numpy(float)),
            }
        )
    return output


def margin_strata(frame: pd.DataFrame) -> dict[str, object]:
    median = float(frame["e2160_margin"].median())
    output: dict[str, object] = {"median_margin": median}
    masks = {
        "lower_or_equal": frame["e2160_margin"] <= median,
        "upper": frame["e2160_margin"] > median,
    }
    for name, mask in masks.items():
        sub = frame.loc[mask]
        x = sub["feature"].to_numpy(float)
        output[name] = {
            "rows": len(sub),
            "net_tercile": tercile_effect(x, sub["net"].to_numpy(float)),
            "adverse_tercile": tercile_effect(x, sub["adverse"].to_numpy(float)),
        }
    return output


def summarize(
    symbol: str,
    frame: pd.DataFrame,
    prefix_frame: pd.DataFrame,
    structural: dict[str, object],
) -> dict[str, object]:
    if len(frame) != len(prefix_frame) or not frame["t"].equals(prefix_frame["t"]):
        raise ValueError(f"{symbol}: opportunity prefix invariance failed")
    numeric = [
        "feature",
        "e2160_margin",
        "gross",
        "net",
        "adverse",
        "delay_net",
        "delay_adverse",
    ]
    if not np.allclose(
        frame[numeric].to_numpy(float),
        prefix_frame[numeric].to_numpy(float),
        rtol=0,
        atol=1e-14,
    ):
        raise ValueError(f"{symbol}: feature/label prefix invariance failed")
    x = frame["feature"].to_numpy(float)
    net = frame["net"].to_numpy(float)
    adverse = frame["adverse"].to_numpy(float)
    delay_net = frame["delay_net"].to_numpy(float)
    delay_adverse = frame["delay_adverse"].to_numpy(float)
    distinct = int(pd.Series(x).nunique())
    iqr = float(np.quantile(x, 0.75) - np.quantile(x, 0.25))
    base_net = triple(x, net)
    base_adverse = triple(x, adverse)
    delayed_net = triple(x, delay_net)
    delayed_adverse = triple(x, delay_adverse)
    intervals = bootstrap_intervals(symbol, x, net, adverse)
    folds = fold_stats(frame)
    negative_net_folds = sum(float(fold["net_slope"]) < 0 for fold in folds)
    negative_adverse_folds = sum(float(fold["adverse_slope"]) < 0 for fold in folds)
    negative_abs = [
        abs(float(fold["net_slope"]))
        for fold in folds
        if float(fold["net_slope"]) < 0
    ]
    concentration = float(max(negative_abs) / sum(negative_abs)) if negative_abs else None
    strata = margin_strata(frame)
    outer_count = len(frame) // 3
    structural_keys = (
        "timestamp_identity",
        "nonnegative_energy",
        "range_share_bounds",
        "positive_price_scale_invariance",
        "zero_total_range_invalidation",
    )
    gates = {
        "opportunities_ge_180": len(frame) >= 180,
        "feature_support": distinct >= 100 and iqr > 0,
        "outer_terciles_ge_50": outer_count >= 50,
        "net_direction": all(base_net[key] < 0 for key in ("rho", "slope", "tercile")),
        "adverse_direction": all(
            base_adverse[key] < 0 for key in ("rho", "slope", "tercile")
        ),
        "dependence_upper_bounds_negative": all(
            intervals[key][1] < 0 for key in intervals
        ),
        "temporal_breadth": negative_net_folds >= 3 and negative_adverse_folds >= 3,
        "negative_net_fold_concentration_le_60pct": (
            concentration is not None and concentration <= 0.60
        ),
        "margin_strata": all(
            float(strata[name][endpoint]) < 0
            for name in ("lower_or_equal", "upper")
            for endpoint in ("net_tercile", "adverse_tercile")
        ),
        "plus_1h_transport": all(value < 0 for value in delayed_net.values())
        and all(value < 0 for value in delayed_adverse.values()),
        "structural_checks": all(bool(structural[key]) for key in structural_keys),
        "prefix_invariance": True,
    }
    return {
        "opportunities": len(frame),
        "feature_distribution": {
            "distinct": distinct,
            "iqr": iqr,
            "min": float(np.min(x)),
            "max": float(np.max(x)),
            "mean": float(np.mean(x)),
        },
        "unconditional_net_return": {
            "mean": float(np.mean(net)),
            "median": float(np.median(net)),
            "positive_fraction": float(np.mean(net > 0)),
        },
        "net_rho": base_net["rho"],
        "net_slope": base_net["slope"],
        "net_tercile_effect": base_net["tercile"],
        "adverse_rho": base_adverse["rho"],
        "adverse_slope": base_adverse["slope"],
        "adverse_tercile_effect": base_adverse["tercile"],
        "bootstrap_95": intervals,
        "folds": folds,
        "negative_net_folds": negative_net_folds,
        "negative_adverse_folds": negative_adverse_folds,
        "negative_net_fold_concentration": concentration,
        "margin_strata": strata,
        "one_hour_delay": {
            "net_rho": delayed_net["rho"],
            "net_slope": delayed_net["slope"],
            "net_tercile_effect": delayed_net["tercile"],
            "adverse_rho": delayed_adverse["rho"],
            "adverse_slope": delayed_adverse["slope"],
            "adverse_tercile_effect": delayed_adverse["tercile"],
        },
        "structural": structural,
        "gates": gates,
        "all_training_gates_pass": all(gates.values()),
    }
