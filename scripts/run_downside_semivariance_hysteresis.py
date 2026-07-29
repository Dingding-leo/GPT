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
PREFIX_BARS = OOS[1] + 1
HASHES = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}
THRESHOLDS = {
    "BTC-USDT": {"reentry_q50": 0.7529914512239673, "exit_q80": 1.2729954105504169},
    "ETH-USDT": {"reentry_q50": 0.7030516429019003, "exit_q80": 1.294158545252833},
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, instrument: str) -> pd.DataFrame:
    if digest(path) != HASHES[instrument]:
        raise ValueError(f"{instrument} hash mismatch")
    # Only the predeclared prefix needed for the final OOS payoff is parsed.
    frame = pd.read_csv(path, nrows=PREFIX_BARS)
    ts = pd.DatetimeIndex(pd.to_datetime(frame.timestamp, utc=True))
    expected = pd.date_range(ts[0], periods=len(ts), freq="1h", tz="UTC")
    valid = len(frame) == PREFIX_BARS and ts.equals(expected) and (frame.confirm == 1).all()
    if not valid:
        raise ValueError(f"{instrument} invalid confirmed 1H prefix chronology")
    frame.index = ts
    return frame


def downside_ratio(close: np.ndarray) -> np.ndarray:
    hourly = np.diff(np.log(close), prepend=np.nan)
    downside_sq = np.where(hourly < 0, hourly * hourly, 0.0)
    downside_sq[0] = np.nan
    recent = pd.Series(downside_sq).rolling(168, min_periods=168).mean().to_numpy()
    slow = pd.Series(downside_sq).rolling(2160, min_periods=2160).mean().to_numpy()
    return np.divide(recent, slow, out=np.full(len(close), np.nan), where=slow > 0)


def positions(
    frame: pd.DataFrame,
    ratio: np.ndarray,
    reentry_threshold: float,
    exit_threshold: float,
) -> tuple[dict[str, np.ndarray], list[dict]]:
    close = frame.close.to_numpy(float)
    ts = frame.index
    n = len(frame)
    out = {name: np.zeros(n - 1) for name in ("candidate", "b0", "b1")}
    candidate = b0 = b1 = 0.0
    risk_lock = False
    events: list[dict] = []

    for t in range(2160, n - 1):
        trend = bool(close[t] > close[t - 2160])
        b0 = float(trend)
        if ts[t].hour == 0:
            b1 = float(trend)
            before = candidate
            event = None
            if candidate == 1.0:
                if not trend:
                    candidate = 0.0
                    risk_lock = False
                    event = "trend_exit"
                elif ratio[t] >= exit_threshold:
                    candidate = 0.0
                    risk_lock = True
                    event = "risk_exit"
            else:
                if not trend:
                    risk_lock = False
                    candidate = 0.0
                elif not risk_lock:
                    candidate = 1.0
                    event = "immediate_trend_entry"
                elif ratio[t] <= reentry_threshold:
                    candidate = 1.0
                    risk_lock = False
                    event = "risk_reentry"
            if event is not None:
                events.append(
                    {
                        "decision_index": t,
                        "timestamp": ts[t].isoformat(),
                        "event": event,
                        "position_before": before,
                        "position_after": candidate,
                        "ratio": float(ratio[t]),
                        "trend_positive": trend,
                    }
                )
        j = t + 1
        if j < n - 1:
            out["candidate"][j] = candidate
            out["b0"][j] = b0
            out["b1"][j] = b1
    return out, events


def series(
    frame: pd.DataFrame, pos: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    market = frame.open.to_numpy(float)[1:] / frame.open.to_numpy(float)[:-1] - 1
    turn = np.r_[abs(pos[0]), np.abs(np.diff(pos))]
    fees = FEE * turn
    gross = pos * market
    return gross - fees, fees, turn, gross


def sharpe(x: np.ndarray) -> float | None:
    std = float(np.std(x, ddof=1))
    return None if std <= 0 else float(math.sqrt(ANN) * np.mean(x) / std)


def metrics(
    net: np.ndarray,
    fees: np.ndarray,
    turn: np.ndarray,
    gross: np.ndarray,
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
        "arithmetic_net_sum": float(x.sum()),
        "gross_sum": float(gross[start:end].sum()),
        "sharpe": sharpe(x),
        "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1)),
        "turnover": turnover,
        "fees": float(fees[start:end].sum()),
        "edge_per_turnover_bps": (float(x.sum() / turnover * 10000) if turnover else None),
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
        "positive_fold_concentration": (max(positive) / sum(positive) if positive else None),
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


def event_diagnostics(
    frame: pd.DataFrame,
    ratio: np.ndarray,
    events: list[dict],
    candidate: np.ndarray,
    b1: np.ndarray,
    cnet: np.ndarray,
    bnet: np.ndarray,
    reentry_threshold: float,
    exit_threshold: float,
) -> dict:
    train_daily = np.array(
        [t for t in range(*TRAIN) if frame.index[t].hour == 0 and np.isfinite(ratio[t])],
        dtype=int,
    )
    oos_daily = np.array(
        [t for t in range(*OOS) if frame.index[t].hour == 0 and np.isfinite(ratio[t])],
        dtype=int,
    )
    start, end = OOS
    market_gross = frame.open.to_numpy(float)[1:] / frame.open.to_numpy(float)[:-1] - 1
    c = candidate[start:end]
    b = b1[start:end]
    candidate_only = (c == 1) & (b == 0)
    b1_only = (b == 1) & (c == 0)
    oos_events = [e for e in events if start <= e["decision_index"] < end]
    event_kinds = (
        "immediate_trend_entry",
        "risk_exit",
        "risk_reentry",
        "trend_exit",
    )
    event_counts = {kind: sum(e["event"] == kind for e in oos_events) for kind in event_kinds}

    risk_windows = []
    for e in oos_events:
        if e["event"] != "risk_exit":
            continue
        # Position change applies at t+1; assess the next 168 market hours
        # from that execution open.
        a = e["decision_index"] + 1
        z = min(a + 168, end)
        if a < end:
            risk_windows.append(float(np.prod(1 + market_gross[a:z]) - 1))

    return {
        "ratio_distribution": {
            "training_median": float(np.median(ratio[train_daily])),
            "oos_median": float(np.median(ratio[oos_daily])),
            "training_q80_exceedance_rate": float(np.mean(ratio[train_daily] >= exit_threshold)),
            "oos_q80_exceedance_rate": float(np.mean(ratio[oos_daily] >= exit_threshold)),
            "training_q50_or_below_rate": float(np.mean(ratio[train_daily] <= reentry_threshold)),
            "oos_q50_or_below_rate": float(np.mean(ratio[oos_daily] <= reentry_threshold)),
        },
        "oos_event_counts": event_counts,
        "candidate_only_hours": int(candidate_only.sum()),
        "candidate_only_market_gross_sum": float(market_gross[start:end][candidate_only].sum()),
        "b1_only_hours": int(b1_only.sum()),
        "b1_only_market_gross_sum": float(market_gross[start:end][b1_only].sum()),
        "candidate_minus_b1_arithmetic_net_sum": float((cnet[start:end] - bnet[start:end]).sum()),
        "risk_exit_next_168h_compounded_market_returns": risk_windows,
        "risk_exit_windows": len(risk_windows),
        "risk_exit_windows_negative": sum(x < 0 for x in risk_windows),
        "risk_exit_window_median": (float(np.median(risk_windows)) if risk_windows else None),
        "risk_exit_window_worst": float(np.min(risk_windows)) if risk_windows else None,
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
        "family_id": "downside-semivariance-hysteresis-trend-carry-1h-v1",
        "issue": 625,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "canonical_fee_one_way": FEE,
        "sample": {
            "training": list(TRAIN),
            "development_oos": list(OOS),
            "full_scored": list(FULL),
            "parsed_prefix_bars": PREFIX_BARS,
            "later_suffix_unread": True,
        },
        "sources": {
            name: {"csv_sha256": HASHES[name], "total_observations": 43941} for name in HASHES
        },
        "markets": {},
    }

    accepted = True
    for name, frame in frames.items():
        ratio = downside_ratio(frame.close.to_numpy(float))
        daily = [t for t in range(*TRAIN) if frame.index[t].hour == 0 and np.isfinite(ratio[t])]
        computed_q50 = float(np.quantile(ratio[daily], 0.50, method="linear"))
        computed_q80 = float(np.quantile(ratio[daily], 0.80, method="linear"))
        frozen = THRESHOLDS[name]
        if not math.isclose(computed_q50, frozen["reentry_q50"], rel_tol=0, abs_tol=1e-15):
            raise ValueError(f"{name} frozen q50 mismatch")
        if not math.isclose(computed_q80, frozen["exit_q80"], rel_tol=0, abs_tol=1e-15):
            raise ValueError(f"{name} frozen q80 mismatch")

        pos, events = positions(frame, ratio, computed_q50, computed_q80)
        packed = {policy: series(frame, values) for policy, values in pos.items()}
        by_span = {}
        spans = (
            ("training", TRAIN),
            ("development_oos", OOS),
            ("full_scored", FULL),
        )
        for label, span in spans:
            by_span[label] = {policy: metrics(*packed[policy], pos[policy], span) for policy in pos}

        cnet = packed["candidate"][0]
        b0net = packed["b0"][0]
        b1net = packed["b1"][0]
        br = breadth(cnet, frame.index)
        boot = bootstrap(cnet, b1net)
        residual_b0 = sharpe(cnet[OOS[0] : OOS[1]] - b0net[OOS[0] : OOS[1]])
        residual_b1 = sharpe(cnet[OOS[0] : OOS[1]] - b1net[OOS[0] : OOS[1]])
        c = by_span["development_oos"]["candidate"]
        b1 = by_span["development_oos"]["b1"]
        concentration = br["positive_fold_concentration"]
        gates = {
            "positive_net_return": c["net_return"] > 0,
            "finite_sharpe_and_exceeds_b1": (
                c["sharpe"] is not None and c["sharpe"] > b1["sharpe"]
            ),
            "edge_per_turnover_exceeds_b1": (
                c["edge_per_turnover_bps"] > b1["edge_per_turnover_bps"]
            ),
            "max_drawdown_no_worse_than_b1": c["max_drawdown"] >= b1["max_drawdown"],
            "long_entries_at_least_8": c["long_entries"] >= 8,
            "profitable_folds_at_least_7_of_12": br["profitable_folds"] >= 7,
            "profitable_years_at_least_3": br["profitable_years"] >= 3,
            "positive_fold_concentration_at_most_50pct": (
                concentration is not None and concentration <= 0.5
            ),
            "positive_residual_sharpe_vs_b0": (residual_b0 is not None and residual_b0 > 0),
            "positive_residual_sharpe_vs_b1": (residual_b1 is not None and residual_b1 > 0),
            "bootstrap_mean_delta_lower_bound_positive": (
                boot["annualized_mean_delta"]["lower_95"] > 0
            ),
            "bootstrap_sharpe_delta_lower_bound_positive": (boot["sharpe_delta"]["lower_95"] > 0),
            "source_chronology_timing_fee_checks": True,
        }
        market_accepted = all(gates.values())
        accepted &= market_accepted
        result["markets"][name] = {
            "thresholds": {"reentry_q50": computed_q50, "exit_q80": computed_q80},
            "metrics": by_span,
            "breadth": br,
            "residual_sharpe_vs_b0": residual_b0,
            "residual_sharpe_vs_b1": residual_b1,
            "bootstrap_vs_b1": boot,
            "risk_diagnostics": event_diagnostics(
                frame,
                ratio,
                events,
                pos["candidate"],
                pos["b1"],
                cnet,
                b1net,
                computed_q50,
                computed_q80,
            ),
            "acceptance_gates": gates,
            "accepted": market_accepted,
        }

    result["accepted"] = accepted
    result["verdict"] = (
        "accept_for_g1_nomination"
        if accepted
        else "reject_exact_downside_semivariance_hysteresis_trend_carry_family"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
