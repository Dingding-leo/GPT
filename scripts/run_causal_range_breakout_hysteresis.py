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
FOLD, ENTRY, EXIT = 2160, 2160, 720
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
        and np.all(df.high.to_numpy(float) >= np.maximum(df.open, df.close))
        and np.all(df.low.to_numpy(float) <= np.minimum(df.open, df.close))
    ):
        raise ValueError(f"{name} invalid confirmed 1H prefix")
    df.index = ts
    return df


def levels(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    high = df.high.to_numpy(float)
    low = df.low.to_numpy(float)
    entry = np.full(len(df), np.nan)
    exit_ = np.full(len(df), np.nan)
    for t in range(ENTRY, len(df)):
        entry[t] = float(np.max(high[t - ENTRY : t]))
        exit_[t] = float(np.min(low[t - EXIT : t]))
    if not np.isnan(entry[:ENTRY]).all() or not np.isfinite(entry[ENTRY:]).all():
        raise ValueError("invalid entry-level chronology")
    if not np.isnan(exit_[:ENTRY]).all() or not np.isfinite(exit_[ENTRY:]).all():
        raise ValueError("invalid exit-level chronology")
    for t in (ENTRY, TRAIN[0], TRAIN[1] - 1, OOS[0], OOS[1] - 1):
        if not math.isclose(entry[t], float(np.max(high[t - ENTRY : t])), abs_tol=1e-12):
            raise ValueError(f"entry parity failure at {t}")
        if not math.isclose(exit_[t], float(np.min(low[t - EXIT : t])), abs_tol=1e-12):
            raise ValueError(f"exit parity failure at {t}")
        if high[t] > entry[t] and math.isclose(entry[t], float(high[t]), abs_tol=1e-12):
            raise ValueError("current high leaked into entry level")
        if low[t] < exit_[t] and math.isclose(exit_[t], float(low[t]), abs_tol=1e-12):
            raise ValueError("current low leaked into exit level")
    return entry, exit_


def positions(df: pd.DataFrame, entry: np.ndarray, exit_: np.ndarray) -> dict[str, np.ndarray]:
    close, n = df.close.to_numpy(float), len(df)
    out = {k: np.zeros(n - 1) for k in ("candidate", "b0", "b1")}
    candidate = b0 = b1 = 0.0
    for t in range(ENTRY, n - 1):
        endpoint = float(close[t] > close[t - ENTRY])
        b0 = endpoint
        if df.index[t].hour == 0:
            if candidate == 0 and close[t] > entry[t]:
                candidate = 1.0
            elif candidate == 1 and close[t] < exit_[t]:
                candidate = 0.0
            b1 = endpoint
        j = t + 1
        if j < n - 1:
            out["candidate"][j], out["b0"][j], out["b1"][j] = candidate, b0, b1
    for policy in ("candidate", "b1"):
        changes = np.flatnonzero(np.r_[out[policy][0] != 0, np.diff(out[policy]) != 0])
        if any(df.index[int(j) - 1].hour != 0 for j in changes if j > 0):
            raise ValueError(f"{policy} changed outside daily next-open boundary")
    if not set(np.unique(out["candidate"])).issubset({0.0, 1.0}):
        raise ValueError("candidate is not long/cash")
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


def metrics(pack: tuple[np.ndarray, ...], pos: np.ndarray, span: tuple[int, int]) -> dict:
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
        "edge_per_turnover_bps": float(x.sum() / turnover * 10000) if turnover else None,
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
        "positive_fold_concentration": max(positive) / sum(positive) if positive else None,
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
        "zero_effect_resample_fraction": float(np.mean(np.isclose(mean_delta, 0.0, atol=1e-15))),
    }


def holding_episodes(net: np.ndarray, pos: np.ndarray, span: tuple[int, int]) -> dict:
    a, z = span
    p = pos[a:z]
    x = net[a:z]
    prior = float(pos[a - 1]) if a else 0.0
    starts = np.flatnonzero((p == 1) & (np.r_[prior, p[:-1]] == 0))
    carried_in = bool(len(p) and p[0] == 1 and prior == 1)
    if carried_in:
        starts = np.r_[0, starts]
    episodes = []
    durations = []
    complete = []
    for start in starts:
        following_cash = np.flatnonzero(p[start:] == 0)
        end = start + int(following_cash[0]) if len(following_cash) else len(p)
        if end <= start:
            continue
        durations.append(end - start)
        episodes.append(float(np.prod(1 + x[start:end]) - 1))
        complete.append(bool((start > 0 or not carried_in) and end < len(p)))
    return {
        "overlapping_episode_count": len(episodes),
        "complete_episode_count": int(sum(complete)),
        "carried_in_episode": carried_in,
        "carried_out_episode": bool(len(p) and p[-1] == 1),
        "median_observed_duration_hours": float(np.median(durations)) if durations else None,
        "mean_observed_duration_hours": float(np.mean(durations)) if durations else None,
        "profitable_observed_episode_ratio": (
            float(np.mean(np.asarray(episodes) > 0)) if episodes else None
        ),
        "median_observed_episode_return": float(np.median(episodes)) if episodes else None,
        "worst_observed_episode_return": float(np.min(episodes)) if episodes else None,
        "best_observed_episode_return": float(np.max(episodes)) if episodes else None,
    }


def diagnostics(
    df: pd.DataFrame,
    entry: np.ndarray,
    exit_: np.ndarray,
    pos: dict,
    pack: dict,
) -> dict:
    close = df.close.to_numpy(float)
    market = df.open.to_numpy(float)[1:] / df.open.to_numpy(float)[:-1] - 1
    daily_train = np.array([t for t in range(*TRAIN) if df.index[t].hour == 0])
    daily_oos = np.array([t for t in range(*OOS) if df.index[t].hour == 0])

    train_breakouts = close[daily_train] > entry[daily_train]
    oos_breakouts = close[daily_oos] > entry[daily_oos]
    train_breakdowns = close[daily_train] < exit_[daily_train]
    oos_breakdowns = close[daily_oos] < exit_[daily_oos]

    candidate = pos["candidate"]
    b1 = pos["b1"]
    a, z = OOS
    candidate_oos, b1_oos = candidate[a:z], b1[a:z]
    market_oos = market[a:z]
    candidate_only = (candidate_oos == 1) & (b1_oos == 0)
    b1_only = (candidate_oos == 0) & (b1_oos == 1)
    candidate_net_oos = pack["candidate"][0][a:z]
    rolling_loss = {}
    log_net = np.log1p(candidate_net_oos)
    for window in (168, 720, 2160):
        compounded = np.expm1(np.convolve(log_net, np.ones(window), mode="valid"))
        rolling_loss[str(window)] = {
            "worst_compounded_return": float(np.min(compounded)),
            "best_compounded_return": float(np.max(compounded)),
        }
    changes = np.flatnonzero(np.r_[candidate[0] != 0, np.diff(candidate) != 0])
    forward_entry, forward_exit, incomplete = [], [], 0
    for j in changes:
        if not (OOS[0] <= j < OOS[1]):
            continue
        if j + 168 > OOS[1]:
            incomplete += 1
            continue
        value = float(np.prod(1 + market[j : j + 168]) - 1)
        (forward_entry if candidate[j] == 1 else forward_exit).append(value)

    return {
        "training_daily_entry_breakout_rate": float(np.mean(train_breakouts)),
        "oos_daily_entry_breakout_rate": float(np.mean(oos_breakouts)),
        "training_daily_exit_breakdown_rate": float(np.mean(train_breakdowns)),
        "oos_daily_exit_breakdown_rate": float(np.mean(oos_breakdowns)),
        "training_candidate_episodes": holding_episodes(pack["candidate"][0], candidate, TRAIN),
        "oos_candidate_episodes": holding_episodes(pack["candidate"][0], candidate, OOS),
        "full_candidate_episodes": holding_episodes(pack["candidate"][0], candidate, FULL),
        "candidate_only_hours_vs_b1_oos": int(candidate_only.sum()),
        "candidate_only_market_gross_sum_oos": float(market_oos[candidate_only].sum()),
        "candidate_only_market_compounded_return_oos": float(
            np.prod(1 + market_oos[candidate_only]) - 1
        ),
        "b1_only_hours_oos": int(b1_only.sum()),
        "b1_only_market_gross_sum_oos": float(market_oos[b1_only].sum()),
        "b1_only_market_compounded_return_oos": float(np.prod(1 + market_oos[b1_only]) - 1),
        "candidate_rolling_return_oos": rolling_loss,
        "complete_entry_168h_windows": len(forward_entry),
        "entry_168h_negative": sum(x < 0 for x in forward_entry),
        "entry_168h_median": float(np.median(forward_entry)) if forward_entry else None,
        "complete_exit_168h_windows": len(forward_exit),
        "exit_168h_negative": sum(x < 0 for x in forward_exit),
        "exit_168h_median": float(np.median(forward_exit)) if forward_exit else None,
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
        "family_id": "causal-range-breakout-hysteresis-trend-1h-v1",
        "issue": 630,
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
        entry, exit_ = levels(df)
        pos = positions(df, entry, exit_)
        pack = {policy: returns(df, values) for policy, values in pos.items()}
        spans = (("training", TRAIN), ("development_oos", OOS), ("full_scored", FULL))
        by_span = {label: {p: metrics(pack[p], pos[p], span) for p in pos} for label, span in spans}
        cnet, b0net, b1net = pack["candidate"][0], pack["b0"][0], pack["b1"][0]
        br, boot = breadth(cnet, df.index), bootstrap(cnet, b1net)
        residual_b0 = sharpe(cnet[OOS[0] : OOS[1]] - b0net[OOS[0] : OOS[1]])
        residual_b1 = sharpe(cnet[OOS[0] : OOS[1]] - b1net[OOS[0] : OOS[1]])
        c, b1 = by_span["development_oos"]["candidate"], by_span["development_oos"]["b1"]
        gates = {
            "positive_net_return": c["net_return"] > 0,
            "positive_sharpe": c["sharpe"] is not None and c["sharpe"] > 0,
            "profitable_folds_at_least_7_of_12": br["profitable_folds"] >= 7,
            "profitable_years_at_least_3": br["profitable_years"] >= 3,
            "positive_fold_concentration_at_most_50pct": (
                br["positive_fold_concentration"] is not None
                and br["positive_fold_concentration"] <= 0.5
            ),
            "max_drawdown_within_2pp_of_b1": c["max_drawdown"] >= b1["max_drawdown"] - 0.02,
            "turnover_no_greater_than_b1": c["turnover"] <= b1["turnover"],
            "positive_edge_per_turnover": c["edge_per_turnover_bps"] is not None
            and c["edge_per_turnover_bps"] > 0,
            "edge_per_turnover_no_worse_than_b1": c["edge_per_turnover_bps"] is not None
            and c["edge_per_turnover_bps"] >= b1["edge_per_turnover_bps"],
            "net_return_no_worse_than_b1": c["net_return"] >= b1["net_return"],
            "sharpe_no_worse_than_b1": c["sharpe"] is not None and c["sharpe"] >= b1["sharpe"],
            "positive_residual_sharpe_vs_b1": residual_b1 is not None and residual_b1 > 0,
            "bootstrap_mean_delta_lower_bound_positive": (
                boot["annualized_mean_delta"]["lower_95"] > 0
            ),
            "bootstrap_sharpe_delta_lower_bound_positive": boot["sharpe_delta"]["lower_95"] > 0,
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
            "diagnostics": diagnostics(df, entry, exit_, pos, pack),
            "acceptance_gates": gates,
            "accepted": market_accepted,
        }
    result["accepted"] = accepted
    result["verdict"] = (
        "accept_for_g1_nomination"
        if accepted
        else "reject_exact_causal_range_breakout_hysteresis_trend_family"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
