from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE, ANN = 0.0005, 8760.0
TRAIN, OOS, FULL = (2880, 17520), (17520, 43440), (2880, 43440)
FOLD, BLOCK, COUNT, WINDOW = 2160, 180, 12, 2160
PREFIX = OOS[1] + 1
HASHES = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}
ARTIFACTS = {"BTC-USDT": 8704977298, "ETH-USDT": 8704978112}


def load(path: Path, name: str) -> pd.DataFrame:
    if hashlib.sha256(path.read_bytes()).hexdigest() != HASHES[name]:
        raise ValueError(f"{name} hash mismatch")
    df = pd.read_csv(path, nrows=PREFIX)
    ts = pd.DatetimeIndex(pd.to_datetime(df.timestamp, utc=True))
    expected = pd.date_range(ts[0], periods=len(ts), freq="1h", tz="UTC")
    prices = df[["open", "high", "low", "close"]].to_numpy(float)
    if not (
        len(df) == PREFIX
        and ts.equals(expected)
        and ts.is_unique
        and (df.confirm == 1).all()
        and np.isfinite(prices).all()
        and (prices > 0).all()
    ):
        raise ValueError(f"{name} invalid confirmed 1H prefix")
    df.index = ts
    return df


def feature(close: np.ndarray) -> np.ndarray:
    logc = np.log(close)
    out = np.full(len(close), np.nan)
    boundaries = np.arange(0, WINDOW + 1, BLOCK)
    for t in range(WINDOW, len(close)):
        out[t] = np.median(np.diff(logc[t - WINDOW + boundaries]) / BLOCK)
    if not np.isnan(out[:WINDOW]).all() or not np.isfinite(out[WINDOW:]).all():
        raise ValueError("invalid feature chronology")
    for t in (WINDOW, TRAIN[0], TRAIN[1] - 1, OOS[0], OOS[1] - 1):
        direct = [
            (logc[t - WINDOW + (j + 1) * BLOCK] - logc[t - WINDOW + j * BLOCK])
            / BLOCK
            for j in range(COUNT)
        ]
        if not math.isclose(out[t], float(np.median(direct)), abs_tol=1e-15):
            raise ValueError(f"feature parity failure at {t}")
    return out


def positions(df: pd.DataFrame, f: np.ndarray) -> dict[str, np.ndarray]:
    close, n = df.close.to_numpy(float), len(df)
    out = {k: np.zeros(n - 1) for k in ("candidate", "b0", "b1")}
    candidate = b0 = b1 = 0.0
    for t in range(WINDOW, n - 1):
        endpoint = float(close[t] > close[t - WINDOW])
        b0 = endpoint
        if df.index[t].hour == 0:
            candidate, b1 = float(f[t] > 0), endpoint
        j = t + 1
        if j < n - 1:
            out["candidate"][j], out["b0"][j], out["b1"][j] = candidate, b0, b1
    changes = np.flatnonzero(
        np.r_[out["candidate"][0] != 0, np.diff(out["candidate"]) != 0]
    )
    if any(df.index[int(j) - 1].hour != 0 for j in changes if j > 0):
        raise ValueError("candidate changed outside daily next-open boundary")
    return out


def returns(df: pd.DataFrame, pos: np.ndarray) -> tuple[np.ndarray, ...]:
    market = df.open.to_numpy(float)[1:] / df.open.to_numpy(float)[:-1] - 1
    turn = np.r_[abs(pos[0]), np.abs(np.diff(pos))]
    fee = FEE * turn
    gross = pos * market
    return gross - fee, fee, turn, gross


def sharpe(x: np.ndarray) -> float | None:
    sd = float(np.std(x, ddof=1))
    return None if sd <= 0 else float(math.sqrt(ANN) * np.mean(x) / sd)


def metrics(
    pack: tuple[np.ndarray, ...], pos: np.ndarray, span: tuple[int, int]
) -> dict:
    net, fee, turn, gross = pack
    a, z = span
    x, p = net[a:z], pos[a:z]
    wealth = np.cumprod(1 + x)
    path = np.r_[1.0, wealth]
    turnover = float(turn[a:z].sum())
    prior = np.r_[pos[a - 1] if a else 0.0, p[:-1]]
    return {
        "net_return": float(wealth[-1] - 1),
        "arithmetic_net_sum": float(x.sum()),
        "gross_sum": float(gross[a:z].sum()),
        "sharpe": sharpe(x),
        "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1)),
        "turnover": turnover,
        "fees": float(fee[a:z].sum()),
        "edge_per_turnover_bps": (
            float(x.sum() / turnover * 10000) if turnover else None
        ),
        "exposure": float(p.mean()),
        "long_entries": int(((p == 1) & (prior == 0)).sum()),
        "position_changes": int((turn[a:z] > 0).sum()),
    }


def breadth(net: np.ndarray, ts: pd.DatetimeIndex) -> dict:
    folds = [
        float(np.prod(1 + net[OOS[0] + k * FOLD : OOS[0] + (k + 1) * FOLD]) - 1)
        for k in range(12)
    ]
    positive = [x for x in folds if x > 0]
    years = {}
    labels = ts[:-1].year
    for year in sorted(set(labels[OOS[0] : OOS[1]])):
        mask = labels[OOS[0] : OOS[1]] == year
        years[str(year)] = float(np.prod(1 + net[OOS[0] : OOS[1]][mask]) - 1)
    return {
        "fold_returns": folds,
        "profitable_folds": sum(x > 0 for x in folds),
        "year_returns": years,
        "profitable_years": sum(x > 0 for x in years.values()),
        "positive_fold_concentration": (
            max(positive) / sum(positive) if positive else None
        ),
    }


def bootstrap(c: np.ndarray, b: np.ndarray) -> dict:
    c, b = c[OOS[0] : OOS[1]], b[OOS[0] : OOS[1]]
    n, rng = len(c), np.random.default_rng(20260729)
    mean_delta, sharpe_delta = np.empty(5000), np.empty(5000)
    offsets = np.arange(168)
    for i in range(5000):
        starts = rng.integers(0, n - 167, size=math.ceil(n / 168))
        idx = (starts[:, None] + offsets).ravel()[:n]
        cr, br = c[idx], b[idx]
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
        "block_hours": 168,
        "resamples": 5000,
        "seed": 20260729,
        "zero_effect_resample_fraction": float(
            np.mean(np.isclose(mean_delta, 0.0, atol=1e-15, rtol=0))
        ),
    }


def run_stats(state: np.ndarray) -> dict:
    boundaries = np.r_[0, np.flatnonzero(np.diff(state) != 0) + 1, len(state)]
    lengths = np.diff(boundaries)
    return {
        "decision_count": int(len(state)),
        "sign_changes": int(np.sum(np.diff(state) != 0)),
        "mean_run_days": float(np.mean(lengths)),
        "median_run_days": float(np.median(lengths)),
        "maximum_run_days": int(np.max(lengths)),
    }


def diagnostics(df: pd.DataFrame, f: np.ndarray, pos: dict, pack: dict) -> dict:
    a, z = OOS
    daily_train = np.array([t for t in range(*TRAIN) if df.index[t].hour == 0])
    daily_oos = np.array([t for t in range(*OOS) if df.index[t].hour == 0])
    close = df.close.to_numpy(float)
    robust_train, robust_oos = f[daily_train] > 0, f[daily_oos] > 0
    endpoint_train = close[daily_train] > close[daily_train - WINDOW]
    endpoint_oos = close[daily_oos] > close[daily_oos - WINDOW]
    candidate, b1 = pos["candidate"][a:z], pos["b1"][a:z]
    market = df.open.to_numpy(float)[1:] / df.open.to_numpy(float)[:-1] - 1
    candidate_only = (candidate == 1) & (b1 == 0)
    b1_only = (candidate == 0) & (b1 == 1)

    changes = np.flatnonzero(
        np.r_[pos["candidate"][0] != 0, np.diff(pos["candidate"]) != 0]
    )
    entry, exit_, incomplete = [], [], 0
    for j in changes:
        if not (a <= j < z):
            continue
        if j + 168 > z:
            incomplete += 1
            continue
        value = float(np.prod(1 + market[j : j + 168]) - 1)
        (entry if pos["candidate"][j] == 1 else exit_).append(value)

    return {
        "training_feature_median": float(np.median(f[daily_train])),
        "oos_feature_median": float(np.median(f[daily_oos])),
        "training_positive_rate": float(np.mean(robust_train)),
        "oos_positive_rate": float(np.mean(robust_oos)),
        "training_disagreement_rate_vs_b1": float(
            np.mean(robust_train != endpoint_train)
        ),
        "oos_disagreement_rate_vs_b1": float(np.mean(robust_oos != endpoint_oos)),
        "candidate_stability": run_stats(robust_oos.astype(int)),
        "b1_stability": run_stats(endpoint_oos.astype(int)),
        "candidate_only_hours": int(candidate_only.sum()),
        "candidate_only_market_gross_sum": float(market[a:z][candidate_only].sum()),
        "b1_only_hours": int(b1_only.sum()),
        "b1_only_market_gross_sum": float(market[a:z][b1_only].sum()),
        "candidate_minus_b1_arithmetic_net_sum": float(
            (pack["candidate"][0][a:z] - pack["b1"][0][a:z]).sum()
        ),
        "complete_entry_168h_windows": len(entry),
        "entry_168h_negative": sum(x < 0 for x in entry),
        "entry_168h_median": float(np.median(entry)) if entry else None,
        "complete_exit_168h_windows": len(exit_),
        "exit_168h_negative": sum(x < 0 for x in exit_),
        "exit_168h_median": float(np.median(exit_)) if exit_ else None,
        "incomplete_168h_windows_excluded": incomplete,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    frames = {
        "BTC-USDT": load(args.btc_csv, "BTC-USDT"),
        "ETH-USDT": load(args.eth_csv, "ETH-USDT"),
    }
    result = {
        "family_id": "robust-distributed-slope-trend-1h-v1",
        "issue": 628,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "canonical_fee_one_way": FEE,
        "sample": {
            "training": list(TRAIN),
            "development_oos": list(OOS),
            "full_scored": list(FULL),
            "fold_count": 12,
            "fold_hours": FOLD,
            "parsed_prefix_bars": PREFIX,
            "later_suffix_unread": True,
        },
        "sources": {
            name: {
                "workflow_run_id": 30401519824,
                "artifact_id": ARTIFACTS[name],
                "csv_sha256": HASHES[name],
                "source_total_observations": 43941,
            }
            for name in HASHES
        },
        "markets": {},
    }
    accepted = True
    for name, df in frames.items():
        f = feature(df.close.to_numpy(float))
        pos = positions(df, f)
        pack = {policy: returns(df, values) for policy, values in pos.items()}
        spans = (
            ("training", TRAIN),
            ("development_oos", OOS),
            ("full_scored", FULL),
        )
        by_span = {
            label: {p: metrics(pack[p], pos[p], span) for p in pos}
            for label, span in spans
        }
        cnet, b0net, b1net = (
            pack["candidate"][0],
            pack["b0"][0],
            pack["b1"][0],
        )
        br, boot = breadth(cnet, df.index), bootstrap(cnet, b1net)
        residual_b0 = sharpe(
            cnet[OOS[0] : OOS[1]] - b0net[OOS[0] : OOS[1]]
        )
        residual_b1 = sharpe(
            cnet[OOS[0] : OOS[1]] - b1net[OOS[0] : OOS[1]]
        )
        c = by_span["development_oos"]["candidate"]
        b1 = by_span["development_oos"]["b1"]
        gates = {
            "positive_net_return": c["net_return"] > 0,
            "positive_sharpe": c["sharpe"] is not None and c["sharpe"] > 0,
            "profitable_folds_at_least_7_of_12": br["profitable_folds"] >= 7,
            "profitable_years_at_least_3": br["profitable_years"] >= 3,
            "positive_fold_concentration_at_most_50pct": br[
                "positive_fold_concentration"
            ]
            <= 0.5,
            "max_drawdown_within_2pp_of_b1": c["max_drawdown"]
            >= b1["max_drawdown"] - 0.02,
            "turnover_no_greater_than_b1": c["turnover"] <= b1["turnover"],
            "positive_edge_per_turnover": c["edge_per_turnover_bps"] > 0,
            "edge_per_turnover_no_worse_than_b1": c["edge_per_turnover_bps"]
            >= b1["edge_per_turnover_bps"],
            "net_return_no_worse_than_b1": c["net_return"] >= b1["net_return"],
            "sharpe_no_worse_than_b1": c["sharpe"] >= b1["sharpe"],
            "positive_residual_sharpe_vs_b1": residual_b1 is not None
            and residual_b1 > 0,
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
            "diagnostics": diagnostics(df, f, pos, pack),
            "acceptance_gates": gates,
            "accepted": market_accepted,
        }
    result["accepted"] = accepted
    result["verdict"] = (
        "accept_for_g1_nomination"
        if accepted
        else "reject_exact_robust_distributed_slope_trend_family"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
