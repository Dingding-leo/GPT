from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE = 0.0005
ANN = 8760.0
TRAIN = (2880, 17520)
OOS = (17520, 43440)
FULL = (2880, 43440)
FOLD = 2160
HASHES = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, instrument: str) -> pd.DataFrame:
    if digest(path) != HASHES[instrument]:
        raise ValueError(f"{instrument} hash mismatch")
    frame = pd.read_csv(path)
    ts = pd.DatetimeIndex(pd.to_datetime(frame.timestamp, utc=True))
    expected = pd.date_range(ts[0], periods=len(ts), freq="1h", tz="UTC")
    if len(frame) != 43941 or not ts.equals(expected) or not (frame.confirm == 1).all():
        raise ValueError(f"{instrument} invalid confirmed 1H chronology")
    frame.index = ts
    return frame


def stress_feature(close: np.ndarray) -> np.ndarray:
    log_close = np.log(close)
    hourly = np.diff(log_close, prepend=np.nan)
    impulse = np.full(len(close), np.nan)
    for s in range(168, len(close)):
        history = hourly[s - 168 : s]
        rms = math.sqrt(float(np.mean(history * history)))
        if rms > 0:
            impulse[s] = (log_close[s - 1] - log_close[s - 25]) / (math.sqrt(24) * rms)
    stress = np.full(len(close), np.nan)
    for t in range(239, len(close)):
        window = impulse[t - 71 : t + 1]
        if np.isfinite(window).all():
            stress[t] = float(np.min(window))
    return stress


def positions(frame: pd.DataFrame, stress: np.ndarray, threshold: float) -> dict[str, np.ndarray]:
    close = frame.close.to_numpy(float)
    ts = frame.index
    n = len(frame)
    out = {name: np.zeros(n - 1) for name in ("candidate", "b0", "b1")}
    candidate = b0 = b1 = 0.0
    for t in range(2160, n - 1):
        trend = close[t] > close[t - 2160]
        b0 = float(trend)
        if ts[t].hour == 0:
            b1 = float(trend)
            if candidate == 0 and trend and stress[t] > threshold:
                candidate = 1.0
            elif candidate == 1 and not trend:
                candidate = 0.0
        j = t + 1
        if j < n - 1:
            out["candidate"][j] = candidate
            out["b0"][j] = b0
            out["b1"][j] = b1
    return out


def series(frame: pd.DataFrame, pos: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    market = frame.open.to_numpy(float)[1:] / frame.open.to_numpy(float)[:-1] - 1
    turn = np.r_[abs(pos[0]), np.abs(np.diff(pos))]
    fees = FEE * turn
    return pos * market - fees, fees, turn


def sharpe(x: np.ndarray) -> float | None:
    std = float(np.std(x, ddof=1))
    return None if std <= 0 else float(math.sqrt(ANN) * np.mean(x) / std)


def metrics(
    net: np.ndarray,
    fees: np.ndarray,
    turn: np.ndarray,
    pos: np.ndarray,
    span: tuple[int, int],
) -> dict:
    start, end = span
    x = net[start:end]
    p = pos[start:end]
    wealth = np.cumprod(1 + x)
    path = np.r_[1.0, wealth]
    turnover = float(turn[start:end].sum())
    prior = np.r_[pos[start - 1] if start else 0.0, p[:-1]]
    return {
        "net_return": float(wealth[-1] - 1),
        "sharpe": sharpe(x),
        "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1)),
        "turnover": turnover,
        "fees": float(fees[start:end].sum()),
        "edge_per_turnover_bps": float(x.sum() / turnover * 10000) if turnover else None,
        "exposure": float(p.mean()),
        "long_entries": int(((p == 1) & (prior == 0)).sum()),
    }


def breadth(net: np.ndarray, ts: pd.DatetimeIndex) -> dict:
    folds = []
    for k in range(12):
        start = OOS[0] + k * FOLD
        folds.append(float(np.prod(1 + net[start : start + FOLD]) - 1))
    positive = [x for x in folds if x > 0]
    years = {}
    year_index = ts[:-1].year
    for year in sorted(set(year_index[OOS[0] : OOS[1]])):
        mask = year_index[OOS[0] : OOS[1]] == year
        years[str(year)] = float(np.prod(1 + net[OOS[0] : OOS[1]][mask]) - 1)
    return {
        "fold_returns": folds,
        "profitable_folds": sum(x > 0 for x in folds),
        "profitable_years": sum(x > 0 for x in years.values()),
        "year_returns": years,
        "positive_fold_concentration": max(positive) / sum(positive) if positive else None,
    }


def bootstrap(candidate: np.ndarray, b1: np.ndarray) -> dict:
    c = candidate[OOS[0] : OOS[1]]
    b = b1[OOS[0] : OOS[1]]
    n = len(c)
    rng = np.random.default_rng(20260729)
    mean_delta = np.empty(5000)
    sharpe_delta = np.empty(5000)
    offsets = np.arange(168)
    for i in range(5000):
        starts = rng.integers(0, n - 167, size=math.ceil(n / 168))
        index = (starts[:, None] + offsets).ravel()[:n]
        cr, br = c[index], b[index]
        mean_delta[i] = ANN * np.mean(cr - br)
        sharpe_delta[i] = (sharpe(cr) or 0.0) - (sharpe(br) or 0.0)
    return {
        "annualized_mean_delta": {
            "point": float(ANN * np.mean(c - b)),
            "lower_95": float(np.quantile(mean_delta, 0.025)),
            "upper_95": float(np.quantile(mean_delta, 0.975)),
        },
        "sharpe_delta": {
            "point": float((sharpe(c) or 0.0) - (sharpe(b) or 0.0)),
            "lower_95": float(np.quantile(sharpe_delta, 0.025)),
            "upper_95": float(np.quantile(sharpe_delta, 0.975)),
        },
        "zero_effect_resample_fraction": float(
            np.mean(np.isclose(mean_delta, 0.0, atol=1e-15, rtol=0))
        ),
        "block_hours": 168,
        "resamples": 5000,
        "seed": 20260729,
    }


def selector_diag(
    frame: pd.DataFrame,
    stress: np.ndarray,
    threshold: float,
    candidate: np.ndarray,
    b1: np.ndarray,
    cnet: np.ndarray,
    bnet: np.ndarray,
) -> dict:
    start, end = OOS
    market = frame.open.to_numpy(float)[1:] / frame.open.to_numpy(float)[:-1] - 1
    delayed = (b1[start:end] == 1) & (candidate[start:end] == 0)
    train_daily = [
        t for t in range(*TRAIN) if frame.index[t].hour == 0 and np.isfinite(stress[t])
    ]
    oos_daily = [
        t for t in range(*OOS) if frame.index[t].hour == 0 and np.isfinite(stress[t])
    ]
    improved = 0
    for k in range(12):
        a = start + k * FOLD
        improved += np.prod(1 + cnet[a : a + FOLD]) > np.prod(1 + bnet[a : a + FOLD])
    return {
        "training_stress_rate": float(np.mean(stress[train_daily] <= threshold)),
        "oos_stress_rate": float(np.mean(stress[oos_daily] <= threshold)),
        "b1_only_delayed_hours": int(delayed.sum()),
        "b1_only_arithmetic_gross_sum": float(market[start:end][delayed].sum()),
        "candidate_minus_b1_arithmetic_net_sum": float(
            (cnet[start:end] - bnet[start:end]).sum()
        ),
        "oos_folds_improved_vs_b1": int(improved),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    btc = load(args.btc_csv, "BTC-USDT")
    eth = load(args.eth_csv, "ETH-USDT")
    stress = stress_feature(btc.close.to_numpy(float))
    daily = [
        t for t in range(*TRAIN) if btc.index[t].hour == 0 and np.isfinite(stress[t])
    ]
    threshold = float(np.quantile(stress[daily], 0.20, method="linear"))
    if threshold != -2.2334011815085733:
        raise ValueError("frozen threshold mismatch")
    result = {
        "family_id": "lagged-btc-stress-entry-veto-1h-v1",
        "issue": 622,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "canonical_fee_one_way": FEE,
        "stress_threshold": threshold,
        "sample": {
            "training": list(TRAIN),
            "development_oos": list(OOS),
            "full_scored": list(FULL),
            "later_suffix_unread": True,
        },
        "sources": {
            name: {"csv_sha256": HASHES[name], "observations": 43941} for name in HASHES
        },
        "markets": {},
    }
    accepted = True
    for name, frame in (("BTC-USDT", btc), ("ETH-USDT", eth)):
        pos = positions(frame, stress, threshold)
        packed = {policy: series(frame, values) for policy, values in pos.items()}
        by_span = {}
        for label, span in (
            ("training", TRAIN),
            ("development_oos", OOS),
            ("full_scored", FULL),
        ):
            by_span[label] = {
                policy: metrics(*packed[policy], pos[policy], span) for policy in pos
            }
        cnet, b0net, b1net = (
            packed["candidate"][0],
            packed["b0"][0],
            packed["b1"][0],
        )
        br = breadth(cnet, frame.index)
        boot = bootstrap(cnet, b1net)
        residual_b0 = sharpe(cnet[OOS[0] : OOS[1]] - b0net[OOS[0] : OOS[1]])
        residual_b1 = sharpe(cnet[OOS[0] : OOS[1]] - b1net[OOS[0] : OOS[1]])
        c = by_span["development_oos"]["candidate"]
        b1 = by_span["development_oos"]["b1"]
        gates = {
            "positive_net_return": c["net_return"] > 0,
            "finite_sharpe_and_exceeds_b1": c["sharpe"] is not None
            and c["sharpe"] > b1["sharpe"],
            "edge_per_turnover_exceeds_b1": c["edge_per_turnover_bps"]
            > b1["edge_per_turnover_bps"],
            "max_drawdown_no_worse_than_b1": c["max_drawdown"] >= b1["max_drawdown"],
            "long_entries_at_least_8": c["long_entries"] >= 8,
            "profitable_folds_at_least_7_of_12": br["profitable_folds"] >= 7,
            "profitable_years_at_least_3": br["profitable_years"] >= 3,
            "positive_fold_concentration_at_most_50pct": br[
                "positive_fold_concentration"
            ]
            <= 0.5,
            "positive_residual_sharpe_vs_b0": residual_b0 > 0,
            "positive_residual_sharpe_vs_b1": residual_b1 > 0,
            "bootstrap_mean_delta_lower_bound_positive": boot[
                "annualized_mean_delta"
            ]["lower_95"]
            > 0,
            "bootstrap_sharpe_delta_lower_bound_positive": boot["sharpe_delta"][
                "lower_95"
            ]
            > 0,
            "source_chronology_timing_fee_checks": True,
        }
        market_accepted = all(gates.values())
        accepted &= market_accepted
        result["markets"][name] = {
            "metrics": by_span,
            "breadth": br,
            "residual_sharpe_vs_b0": residual_b0,
            "residual_sharpe_vs_b1": residual_b1,
            "bootstrap_vs_b1": boot,
            "selector_diagnostics": selector_diag(
                frame,
                stress,
                threshold,
                pos["candidate"],
                pos["b1"],
                cnet,
                b1net,
            ),
            "acceptance_gates": gates,
            "accepted": market_accepted,
        }
    result["accepted"] = accepted
    result["verdict"] = (
        "accept_for_g1_nomination"
        if accepted
        else "reject_exact_lagged_btc_stress_entry_veto_family"
    )
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
