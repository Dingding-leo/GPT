# ruff: noqa: E501
# fmt: off
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE, ANN = (0.0005, 8760.0)
TRAIN, OOS, FULL = ((2880, 17520), (17520, 43440), (2880, 43440))
WINDOW, FOLD, PREFIX = (2160, 2160, 43441)
HASH = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}
ART = {"BTC-USDT": 8704977298, "ETH-USDT": 8704978112}
BOUNDARY = {
    "BTC-USDT": {"entry": 0.7579595282504553, "exit": 0.5839852313597377},
    "ETH-USDT": {"entry": 0.6968985403690291, "exit": 0.5474091765147670},
}


def fixed_basis() -> np.ndarray:
    u = np.linspace(-1.0, 1.0, WINDOW)
    raw = np.column_stack(
        [
            np.ones(WINDOW),
            u,
            0.5 * (3.0 * u**2 - 1.0),
            0.5 * (5.0 * u**3 - 3.0 * u),
            (35.0 * u**4 - 30.0 * u**2 + 3.0) / 8.0,
        ]
    )
    q, _ = np.linalg.qr(raw)
    if float(q[:, 1] @ u) < 0:
        q[:, 1] *= -1.0
    if not np.allclose(q.T @ q, np.eye(5), atol=1e-12, rtol=0):
        raise ValueError("basis orthogonality")
    return q[:, 1:5]


BASIS = fixed_basis()


def load(p: Path, n: str) -> pd.DataFrame:
    if hashlib.sha256(p.read_bytes()).hexdigest() != HASH[n]:
        raise ValueError(f"{n} hash")
    d = pd.read_csv(p, nrows=PREFIX)
    t = pd.DatetimeIndex(pd.to_datetime(d.timestamp, utc=True))
    x = d[["open", "high", "low", "close"]].to_numpy(float)
    ok = (
        len(d) == PREFIX
        and t.equals(pd.date_range(t[0], periods=len(t), freq="1h", tz="UTC"))
        and t.is_unique
        and (d.confirm == 1).all()
        and np.isfinite(x).all()
        and (x > 0).all()
        and (d.high >= d.low).all()
    )
    if not ok:
        raise ValueError(f"{n} invalid")
    d.index = t
    return d


def daily_features(d: pd.DataFrame) -> dict[int, tuple[float, float, tuple[float, ...]]]:
    lp = np.log(d.close.to_numpy(float))
    out: dict[int, tuple[float, float, tuple[float, ...]]] = {}
    for t in range(WINDOW - 1, len(d) - 1):
        if d.index[t].hour != 0:
            continue
        y = lp[t - WINDOW + 1 : t + 1]
        y = y - float(y.mean())
        coef = BASIS.T @ y
        energy = coef * coef
        den = float(energy.sum())
        coherence = float(energy[0] / den) if den > 0 else 0.0
        out[t] = (float(coef[0]), coherence, tuple(float(v) for v in coef))
    return out


def validate_training_boundary(features: dict[int, tuple[float, float, tuple[float, ...]]], n: str) -> dict[str, float | int]:
    vals = [(t, s, c) for t, (s, c, _) in features.items() if TRAIN[0] <= t < TRAIN[1]]
    pos = np.array([c for _, s, c in vals if s > 0], dtype=float)
    entry = float(np.quantile(pos, 0.70))
    exit_ = float(np.quantile(pos, 0.45))
    if not math.isclose(entry, BOUNDARY[n]["entry"], rel_tol=0, abs_tol=1e-15):
        raise ValueError(f"{n} entry boundary")
    if not math.isclose(exit_, BOUNDARY[n]["exit"], rel_tol=0, abs_tol=1e-15):
        raise ValueError(f"{n} exit boundary")
    q = 0.0
    entries = exits = long_count = decisions = 0
    for t, (slope, coherence, _) in features.items():
        if t >= TRAIN[1]:
            break
        old = q
        if q == 0 and slope > 0 and coherence >= entry:
            q = 1.0
        elif q == 1 and (slope <= 0 or coherence <= exit_):
            q = 0.0
        if t >= TRAIN[0]:
            entries += int(old == 0 and q == 1)
            exits += int(old == 1 and q == 0)
            long_count += int(q == 1)
            decisions += 1
    if decisions != len(vals):
        raise ValueError(f"{n} training decision count")
    return {
        "daily_decisions": len(vals),
        "positive_slope_decisions": int(len(pos)),
        "entry_boundary_q70": entry,
        "exit_boundary_q45": exit_,
        "state_entries": entries,
        "state_exits": exits,
        "daily_target_exposure": float(long_count / decisions),
        "state_carried_from_pretraining_history": True,
    }


def positions(d: pd.DataFrame, n: str, features: dict[int, tuple[float, float, tuple[float, ...]]]) -> dict[str, np.ndarray]:
    c = d.close.to_numpy(float)
    m = len(d)
    out = {k: np.zeros(m - 1) for k in ("candidate", "b0", "b1")}
    q = b0 = b1 = 0.0
    for t in range(WINDOW, m - 1):
        b0 = float(c[t] > c[t - WINDOW])
        if d.index[t].hour == 0:
            slope, coherence, _ = features[t]
            old = q
            if q == 0 and slope > 0 and coherence >= BOUNDARY[n]["entry"]:
                q = 1.0
            elif q == 1 and (slope <= 0 or coherence <= BOUNDARY[n]["exit"]):
                q = 0.0
            b1 = b0
            if old != q:
                valid = (q == 1 and slope > 0 and coherence >= BOUNDARY[n]["entry"]) or (
                    q == 0 and (slope <= 0 or coherence <= BOUNDARY[n]["exit"])
                )
                if not valid:
                    raise ValueError("transition")
        j = t + 1
        if j < m - 1:
            out["candidate"][j], out["b0"][j], out["b1"][j] = (q, b0, b1)
    ch = np.flatnonzero(np.r_[out["candidate"][0] != 0, np.diff(out["candidate"]) != 0])
    if any(j <= 0 or d.index[int(j) - 1].hour != 0 for j in ch):
        raise ValueError("timing")
    return out


def pack(d: pd.DataFrame, p: np.ndarray) -> tuple[np.ndarray, ...]:
    o = d.open.to_numpy(float)
    market = o[1:] / o[:-1] - 1.0
    turnover = np.r_[abs(p[0]), np.abs(np.diff(p))]
    gross = p * market
    fees = FEE * turnover
    return (gross - fees, fees, turnover, gross, market)


def sharpe(x: np.ndarray) -> float | None:
    s = float(np.std(x, ddof=1))
    return None if s <= 0 else float(math.sqrt(ANN) * np.mean(x) / s)


def metrics(a: tuple[np.ndarray, ...], p: np.ndarray, span: tuple[int, int]) -> dict[str, float | int | None]:
    net, fees, turnover, gross, _ = a
    i, j = span
    x = net[i:j]
    z = p[i:j]
    wealth = np.cumprod(1.0 + x)
    path = np.r_[1.0, wealth]
    tv = float(turnover[i:j].sum())
    prior = np.r_[p[i - 1] if i else 0.0, z[:-1]]
    return {
        "net_return": float(wealth[-1] - 1.0),
        "arithmetic_net_sum": float(x.sum()),
        "gross_sum": float(gross[i:j].sum()),
        "sharpe": sharpe(x),
        "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1.0)),
        "turnover": tv,
        "fees": float(fees[i:j].sum()),
        "edge_per_turnover_bps": float(x.sum() / tv * 10000.0) if tv else None,
        "exposure": float(z.mean()),
        "long_entries": int(((z == 1) & (prior == 0)).sum()),
        "position_changes": int((turnover[i:j] > 0).sum()),
    }


def breadth(net: np.ndarray, ts: pd.DatetimeIndex) -> dict[str, object]:
    fold_returns = [
        float(np.prod(1.0 + net[OOS[0] + k * FOLD : OOS[0] + (k + 1) * FOLD]) - 1.0)
        for k in range(12)
    ]
    positive = [x for x in fold_returns if x > 0]
    year_returns: dict[str, float] = {}
    labels = ts[:-1].year
    for year in sorted(set(labels[OOS[0] : OOS[1]])):
        mask = labels[OOS[0] : OOS[1]] == year
        year_returns[str(year)] = float(np.prod(1.0 + net[OOS[0] : OOS[1]][mask]) - 1.0)
    return {
        "fold_returns": fold_returns,
        "profitable_folds": sum(x > 0 for x in fold_returns),
        "year_returns": year_returns,
        "profitable_years": sum(x > 0 for x in year_returns.values()),
        "positive_fold_concentration": max(positive) / sum(positive) if positive else None,
    }


def bootstrap(candidate: np.ndarray, b1: np.ndarray) -> dict[str, object]:
    candidate, b1 = (candidate[OOS[0] : OOS[1]], b1[OOS[0] : OOS[1]])
    n = len(candidate)
    rng = np.random.default_rng(20260730)
    mean_delta = np.empty(5000)
    sharpe_delta = np.empty(5000)
    offsets = np.arange(168)
    for i in range(5000):
        starts = rng.integers(0, n - 167, size=math.ceil(n / 168))
        ix = (starts[:, None] + offsets).ravel()[:n]
        cr, br = candidate[ix], b1[ix]
        mean_delta[i] = ANN * np.mean(cr - br)
        sharpe_delta[i] = (sharpe(cr) or 0.0) - (sharpe(br) or 0.0)
    return {
        "annualized_mean_delta": {
            "point": float(ANN * np.mean(candidate - b1)),
            "lower_95": float(np.quantile(mean_delta, 0.025)),
            "upper_95": float(np.quantile(mean_delta, 0.975)),
        },
        "sharpe_delta": {
            "point": float((sharpe(candidate) or 0.0) - (sharpe(b1) or 0.0)),
            "lower_95": float(np.quantile(sharpe_delta, 0.025)),
            "upper_95": float(np.quantile(sharpe_delta, 0.975)),
        },
        "block_hours": 168,
        "resamples": 5000,
        "seed": 20260730,
    }


def episodes(pos: np.ndarray, net: np.ndarray, ts: pd.DatetimeIndex) -> dict[str, object]:
    a, z = OOS
    p = pos[a:z]
    x = net[a:z]
    boundaries = np.r_[0, np.flatnonzero(np.diff(p) != 0) + 1, len(p)]
    result = []
    for s, e in zip(boundaries[:-1], boundaries[1:], strict=True):
        if p[s] == 1:
            result.append(
                {
                    "start": str(ts[a + s]),
                    "stop": str(ts[a + e]),
                    "hours": int(e - s),
                    "net_return": float(np.prod(1.0 + x[s:e]) - 1.0),
                }
            )
    returns = [e["net_return"] for e in result]
    durations = [e["hours"] for e in result]
    return {
        "overlapping_oos_episodes": len(result),
        "episodes": result,
        "median_duration_hours": float(np.median(durations)) if result else None,
        "profitable_episode_ratio": float(np.mean(np.array(returns) > 0)) if result else None,
        "worst_episode_return": min(returns) if result else None,
    }


def diagnostics(
    d: pd.DataFrame,
    n: str,
    features: dict[int, tuple[float, float, tuple[float, ...]]],
    pos: dict[str, np.ndarray],
    packed: dict[str, tuple[np.ndarray, ...]],
) -> dict[str, object]:
    a, z = OOS
    candidate = pos["candidate"][a:z]
    b1 = pos["b1"][a:z]
    market = packed["candidate"][4][a:z]
    candidate_only = (candidate == 1) & (b1 == 0)
    b1_only = (candidate == 0) & (b1 == 1)

    def feature_summary(span: tuple[int, int]) -> dict[str, float | int]:
        vals = [(s, c) for t, (s, c, _) in features.items() if span[0] <= t < span[1]]
        slopes = np.array([s for s, _ in vals])
        coherence = np.array([c for _, c in vals])
        positive = coherence[slopes > 0]
        return {
            "daily_decisions": len(vals),
            "positive_slope_rate": float(np.mean(slopes > 0)),
            "coherence_median_all": float(np.median(coherence)),
            "coherence_median_positive_slope": float(np.median(positive)) if len(positive) else None,
            "entry_boundary_exceedance_rate_positive_slope": float(np.mean(positive >= BOUNDARY[n]["entry"])) if len(positive) else None,
            "exit_boundary_breach_rate_positive_slope": float(np.mean(positive <= BOUNDARY[n]["exit"])) if len(positive) else None,
        }

    cp = pos["candidate"]
    daily_oos = np.array([t for t in range(*OOS) if d.index[t].hour == 0])

    transitions = []
    for t in daily_oos:
        j = t + 1
        if j >= len(cp):
            continue
        previous = cp[j - 1]
        current = cp[j]
        if previous == current:
            continue
        slope, coherence, _ = features[t]
        h = min(168, len(market) - (j - a))
        forward_market = float(np.prod(1.0 + market[j - a : j - a + h]) - 1.0) if h > 0 else None
        transitions.append(
            {
                "signal_bar": str(d.index[t]),
                "transition": "entry" if current == 1 else "exit",
                "slope": slope,
                "coherence": coherence,
                "forward_market_return_168h_or_available": forward_market,
            }
        )

    net = packed["candidate"][0][a:z]

    def worst(hours: int) -> float:
        return float(min(np.prod(1.0 + net[i : i + hours]) - 1.0 for i in range(len(net) - hours + 1)))

    return {
        "feature_drift": {"training": feature_summary(TRAIN), "development_oos": feature_summary(OOS)},
        "candidate_only_hours": int(candidate_only.sum()),
        "candidate_only_market_gross_sum": float(market[candidate_only].sum()),
        "b1_only_hours": int(b1_only.sum()),
        "b1_only_market_gross_sum": float(market[b1_only].sum()),
        "transitions": transitions,
        "entry_count_oos": sum(x["transition"] == "entry" for x in transitions),
        "exit_count_oos": sum(x["transition"] == "exit" for x in transitions),
        "post_entry_positive_168h_ratio": float(np.mean([x["forward_market_return_168h_or_available"] > 0 for x in transitions if x["transition"] == "entry"])) if any(x["transition"] == "entry" for x in transitions) else None,
        "post_exit_negative_168h_ratio": float(np.mean([x["forward_market_return_168h_or_available"] < 0 for x in transitions if x["transition"] == "exit"])) if any(x["transition"] == "exit" for x in transitions) else None,
        "worst_rolling_168h_candidate_return": worst(168),
        "worst_rolling_720h_candidate_return": worst(720),
        "episodes": episodes(cp, packed["candidate"][0], d.index),
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
    result: dict[str, object] = {
        "family_id": "low-frequency-trend-coherence-hysteresis-1h-v1",
        "issue": 634,
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
            n: {
                "workflow_run_id": 30401519824,
                "artifact_id": ART[n],
                "csv_sha256": HASH[n],
                "source_total_observations": 43941,
            }
            for n in HASH
        },
        "basis": {
            "grid": "2160 fixed equally spaced points in [-1,1]",
            "raw_columns": ["P0", "P1", "P2", "P3", "P4"],
            "orthonormalization": "numpy.linalg.qr in fixed column order",
            "trend_basis": "oriented P1 column",
            "low_frequency_residual_basis": ["P2", "P3", "P4"],
            "max_orthogonality_error": float(np.max(np.abs(np.column_stack([np.ones(WINDOW) / math.sqrt(WINDOW), BASIS]).T @ np.column_stack([np.ones(WINDOW) / math.sqrt(WINDOW), BASIS]) - np.eye(5)))),
        },
        "boundaries": BOUNDARY,
        "diagnostic_correction": {
            "description": "Freeze-time training state diagnostics initially reset state at the training boundary. Canonical accounting was repaired to carry state from the first eligible pretraining decision, as required by the frozen rule.",
            "BTC_state_entries_exits_before": [2, 2],
            "BTC_state_entries_exits_after": [2, 3],
            "BTC_daily_target_exposure_before": 0.16885245901639345,
            "BTC_daily_target_exposure_after": 0.1918032786885246,
            "strategy_features_positions_returns_fees_comparators_gates_bootstrap_verdict_changed": False,
            "development_oos_or_later_suffix_used_for_repair": False,
        },
        "markets": {},
    }

    accepted = True
    for n, d in frames.items():
        feature = daily_features(d)
        training_feature_validation = validate_training_boundary(feature, n)
        pos = positions(d, n, feature)
        packed = {k: pack(d, v) for k, v in pos.items()}
        spans = (("training", TRAIN), ("development_oos", OOS), ("full_scored", FULL))
        all_metrics = {label: {k: metrics(packed[k], pos[k], span) for k in pos} for label, span in spans}
        candidate_net, b0_net, b1_net = (packed["candidate"][0], packed["b0"][0], packed["b1"][0])
        br = breadth(candidate_net, d.index)
        bt = bootstrap(candidate_net, b1_net)
        residual_b0 = sharpe(candidate_net[OOS[0] : OOS[1]] - b0_net[OOS[0] : OOS[1]])
        residual_b1 = sharpe(candidate_net[OOS[0] : OOS[1]] - b1_net[OOS[0] : OOS[1]])
        candidate = all_metrics["development_oos"]["candidate"]
        b1 = all_metrics["development_oos"]["b1"]
        gates = {
            "positive_net_return": candidate["net_return"] > 0,
            "positive_sharpe": candidate["sharpe"] is not None and candidate["sharpe"] > 0,
            "profitable_folds_at_least_7_of_12": br["profitable_folds"] >= 7,
            "profitable_years_at_least_3": br["profitable_years"] >= 3,
            "positive_fold_concentration_at_most_50pct": br["positive_fold_concentration"] is not None and br["positive_fold_concentration"] <= 0.5,
            "max_drawdown_within_2pp_of_b1": candidate["max_drawdown"] >= b1["max_drawdown"] - 0.02,
            "turnover_no_greater_than_b1": candidate["turnover"] <= b1["turnover"],
            "positive_edge_per_turnover": candidate["edge_per_turnover_bps"] is not None and candidate["edge_per_turnover_bps"] > 0,
            "edge_per_turnover_no_worse_than_b1": candidate["edge_per_turnover_bps"] is not None and candidate["edge_per_turnover_bps"] >= b1["edge_per_turnover_bps"],
            "net_return_no_worse_than_b1": candidate["net_return"] >= b1["net_return"],
            "sharpe_no_worse_than_b1": candidate["sharpe"] is not None and candidate["sharpe"] >= b1["sharpe"],
            "positive_residual_sharpe_vs_b1": residual_b1 is not None and residual_b1 > 0,
            "bootstrap_mean_delta_lower_bound_positive": bt["annualized_mean_delta"]["lower_95"] > 0,
            "bootstrap_sharpe_delta_lower_bound_positive": bt["sharpe_delta"]["lower_95"] > 0,
            "source_chronology_timing_fee_checks": True,
        }
        ok = all(gates.values())
        accepted &= ok
        result["markets"][n] = {
            "training_feature_validation": training_feature_validation,
            "metrics": all_metrics,
            "breadth": br,
            "residual_sharpe_vs_b0": residual_b0,
            "residual_sharpe_vs_b1": residual_b1,
            "bootstrap_vs_b1": bt,
            "diagnostics": diagnostics(d, n, feature, pos, packed),
            "acceptance_gates": gates,
            "accepted": ok,
        }
    result["accepted"] = accepted
    result["verdict"] = (
        "accept_for_g1_nomination"
        if accepted
        else "reject_exact_low_frequency_trend_coherence_hysteresis_family"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
