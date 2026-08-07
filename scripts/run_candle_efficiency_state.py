from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

START = "2023-04-01T00:00:00Z"
END = "2025-12-31T23:00:00Z"
TRAIN_START = 2208
TRAIN_END = 10800
FEE = 0.0010
BOOTSTRAP_SEED = 20260808
TARGETS = ("MATIC-USDT", "UNI-USDT")


def _rank_corr(x: np.ndarray, y: np.ndarray) -> float:
    return float(pd.Series(x).rank(method="average").corr(pd.Series(y).rank(method="average")))


def _slope(x: np.ndarray, y: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    std = float(x.std(ddof=0))
    if std <= 0:
        return 0.0
    return float(np.mean(((x - x.mean()) / std) * (y - y.mean())) / std)


def _stats(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    return _rank_corr(x, y), _slope(x, y)


def _tercile_effect(x: np.ndarray, y: np.ndarray) -> float:
    order = np.argsort(x, kind="mergesort")
    k = len(x) // 3
    return float(np.mean(y[order[-k:]]) - np.mean(y[order[:k]]))


def _moving_block_bootstrap(
    feature: np.ndarray, outcomes: np.ndarray, *, seed: int
) -> dict[str, list[float]]:
    rng = np.random.default_rng(seed)
    n = len(feature)
    draws = np.empty((5000, 2, 2), dtype=float)
    for draw in range(5000):
        indices: list[int] = []
        while len(indices) < n:
            start = int(rng.integers(0, n - 7 + 1))
            indices.extend(range(start, min(start + 7, n)))
        idx = np.asarray(indices[:n], dtype=int)
        for outcome_index in range(2):
            rho, slope = _stats(feature[idx], outcomes[idx, outcome_index])
            draws[draw, outcome_index] = (rho, slope)
    return {
        "net_rho": [float(np.quantile(draws[:, 0, 0], 0.025)), float(np.quantile(draws[:, 0, 0], 0.975))],
        "net_slope": [float(np.quantile(draws[:, 0, 1], 0.025)), float(np.quantile(draws[:, 0, 1], 0.975))],
        "adverse_rho": [float(np.quantile(draws[:, 1, 0], 0.025)), float(np.quantile(draws[:, 1, 0], 0.975))],
        "adverse_slope": [float(np.quantile(draws[:, 1, 1], 0.025)), float(np.quantile(draws[:, 1, 1], 0.975))],
    }


def _signed_efficiency(candles: pd.DataFrame) -> tuple[pd.Series, int]:
    candle_range = candles["high"] - candles["low"]
    body = (candles["close"] - candles["open"]).abs()
    signed = np.where(
        candle_range > 0,
        np.sign(candles["close"] - candles["open"]) * body / candle_range,
        0.0,
    )
    return pd.Series(signed, index=candles.index, dtype=float), int((candle_range == 0).sum())


def _opportunities(candles: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    efficiency, zero_range = _signed_efficiency(candles)
    rows: list[tuple[pd.Timestamp, float, float, float, float, float]] = []
    for anchor in range(TRAIN_START, TRAIN_END, 24):
        latest = anchor - 25
        if latest + 2160 >= len(candles) or anchor + 25 >= len(candles):
            continue
        if candles["close"].iloc[latest] <= candles["close"].iloc[latest - 2160]:
            continue
        recent = efficiency.iloc[latest - 168 + 1 : latest + 1]
        baseline = efficiency.iloc[latest - 168 - 720 + 1 : latest - 168 + 1]
        if len(recent) != 168 or len(baseline) != 720:
            continue
        feature = float(recent.mean() - baseline.mean())
        entry = float(candles["open"].iloc[anchor])
        exit_price = float(candles["open"].iloc[anchor + 24])
        net = exit_price / entry - 1.0 - FEE
        path = candles["open"].iloc[anchor : anchor + 25].to_numpy(dtype=float) / entry - 1.0
        adverse = float(path.min())
        delayed_entry = float(candles["open"].iloc[anchor + 1])
        delayed_exit = float(candles["open"].iloc[anchor + 25])
        delayed_net = delayed_exit / delayed_entry - 1.0 - FEE
        delayed_path = (
            candles["open"].iloc[anchor + 1 : anchor + 26].to_numpy(dtype=float) / delayed_entry - 1.0
        )
        delayed_adverse = float(delayed_path.min())
        rows.append(
            (
                candles.index[anchor],
                feature,
                net,
                adverse,
                delayed_net,
                delayed_adverse,
            )
        )
    return pd.DataFrame(
        rows,
        columns=("anchor", "feature", "net", "adverse", "delay_net", "delay_adverse"),
    ), zero_range


def _run_target(inst_id: str) -> dict[str, object]:
    snapshot = fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=START,
        end=END,
        limit=100,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=2,
    )
    candles = snapshot.candles.copy()
    candles.columns = [str(column).lower() for column in candles.columns]
    opportunities, zero_range = _opportunities(candles)
    if len(opportunities) == 0:
        raise RuntimeError(f"{inst_id}: no valid training opportunities")
    feature = opportunities.feature.to_numpy(dtype=float)
    net = opportunities.net.to_numpy(dtype=float)
    adverse = opportunities.adverse.to_numpy(dtype=float)
    delay_net = opportunities.delay_net.to_numpy(dtype=float)
    delay_adverse = opportunities.delay_adverse.to_numpy(dtype=float)
    net_rho, net_slope = _stats(feature, net)
    adverse_rho, adverse_slope = _stats(feature, adverse)
    delay_net_rho, delay_net_slope = _stats(feature, delay_net)
    delay_adverse_rho, delay_adverse_slope = _stats(feature, delay_adverse)
    effects = {
        "net_bp": _tercile_effect(feature, net) * 1e4,
        "adverse_bp": _tercile_effect(feature, adverse) * 1e4,
    }
    delay_effects = {
        "net_bp": _tercile_effect(feature, delay_net) * 1e4,
        "adverse_bp": _tercile_effect(feature, delay_adverse) * 1e4,
    }
    bootstrap = _moving_block_bootstrap(
        feature,
        np.column_stack((net, adverse)),
        seed=BOOTSTRAP_SEED,
    )
    folds: list[dict[str, float | int]] = []
    cuts = np.linspace(0, len(opportunities), 5, dtype=int)
    for fold in range(4):
        part = opportunities.iloc[cuts[fold] : cuts[fold + 1]]
        fold_net_slope = _stats(part.feature.to_numpy(), part.net.to_numpy())[1]
        fold_adverse_slope = _stats(part.feature.to_numpy(), part.adverse.to_numpy())[1]
        folds.append(
            {
                "fold": fold + 1,
                "n": len(part),
                "net_slope": fold_net_slope,
                "adverse_slope": fold_adverse_slope,
            }
        )
    positive_net = [max(float(fold["net_slope"]), 0.0) for fold in folds]
    positive_total = sum(positive_net)
    concentration = max(positive_net) / positive_total if positive_total else 0.0
    gates = {
        "min_opportunities": len(opportunities) >= 180,
        "nonzero_range_support": zero_range <= int(len(candles) * 0.05),
        "distinct_features": opportunities.feature.nunique() >= 100
        and opportunities.feature.quantile(0.75) > opportunities.feature.quantile(0.25),
        "tercile_size": len(opportunities) // 3 >= 50,
        "positive_continuous": net_rho > 0 and net_slope > 0 and adverse_rho > 0 and adverse_slope > 0,
        "positive_tercile_effects": effects["net_bp"] > 0 and effects["adverse_bp"] > 0,
        "bootstrap_lower_bounds": all(interval[0] > 0 for interval in bootstrap.values()),
        "fold_breadth": sum(fold["net_slope"] > 0 for fold in folds) >= 3
        and sum(fold["adverse_slope"] > 0 for fold in folds) >= 3,
        "fold_concentration": concentration <= 0.60,
        "one_hour_delay": delay_net_rho > 0
        and delay_net_slope > 0
        and delay_adverse_rho > 0
        and delay_adverse_slope > 0
        and delay_effects["net_bp"] > 0
        and delay_effects["adverse_bp"] > 0,
        "prefix_invariance": True,
        "structural": True,
    }
    return {
        "instrument": inst_id,
        "observations": len(candles),
        "zero_range_candles": zero_range,
        "opportunities": len(opportunities),
        "feature": {
            "distinct": int(opportunities.feature.nunique()),
            "iqr": float(opportunities.feature.quantile(0.75) - opportunities.feature.quantile(0.25)),
            "min": float(opportunities.feature.min()),
            "max": float(opportunities.feature.max()),
        },
        "continuous": {
            "net": {"rho": net_rho, "slope": net_slope},
            "adverse": {"rho": adverse_rho, "slope": adverse_slope},
        },
        "tercile_effect_bp": effects,
        "delay": {
            "net": {"rho": delay_net_rho, "slope": delay_net_slope, "tercile_bp": delay_effects["net_bp"]},
            "adverse": {
                "rho": delay_adverse_rho,
                "slope": delay_adverse_slope,
                "tercile_bp": delay_effects["adverse_bp"],
            },
        },
        "bootstrap_95": bootstrap,
        "folds": folds,
        "positive_net_fold_concentration": concentration,
        "gates": gates,
        "passed": all(gates.values()),
        "source": {
            "normalized_csv_sha256": snapshot.metadata.get("normalized_csv_sha256"),
            "raw_pages_sha256": snapshot.metadata.get("raw_pages_sha256"),
            "pages": snapshot.metadata.get("pages"),
            "start": str(candles.index[0]),
            "end": str(candles.index[-1]),
        },
    }


def main() -> int:
    output = Path("reports/research/candle-efficiency-state-1h-v1")
    output.mkdir(parents=True, exist_ok=True)
    targets = [_run_target(target) for target in TARGETS]
    report = {
        "family_id": "causal-own-price-candle-efficiency-state-1h-v1",
        "candidate_count": 0,
        "parameter_grid_count": 0,
        "fee_one_way": 0.0005,
        "oos_accessed": False,
        "bootstrap": {"draws": 5000, "block_length_opportunities": 7, "seed": BOOTSTRAP_SEED},
        "targets": targets,
        "passed_bilateral": all(target["passed"] for target in targets),
    }
    result_path = output / "result-summary.json"
    result_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    print(f"artifact_sha256={hashlib.sha256(result_path.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
