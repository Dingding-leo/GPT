from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE, ANN = 5e-4, 8760.0
TREND, HIGH_WINDOW, DROUGHT, RETURN_WINDOW = 2160, 720, 168, 168
N, FOLD, BLOCK, RESAMPLES, SEED = 43441, 2160, 168, 5000, 20260730
TRAIN, OOS, FULL = (2880, 17520), (17520, 43440), (2880, 43440)
HASHES = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, market: str) -> pd.DataFrame:
    actual = sha256(path)
    if actual != HASHES[market]:
        raise ValueError(f"{market} hash mismatch: {actual}")
    d = pd.read_csv(path, nrows=N)
    t = pd.DatetimeIndex(pd.to_datetime(d.timestamp, utc=True))
    num = d[["open", "high", "low", "close", "volume_quote"]].to_numpy(float)
    valid = (
        len(d) == N
        and t.equals(pd.date_range(t[0], periods=N, freq="1h", tz="UTC"))
        and t.is_unique
        and (d.confirm == 1).all()
        and np.isfinite(num).all()
        and (num[:, :4] > 0).all()
        and (num[:, 4] >= 0).all()
        and (d.high >= d[["open", "close"]].max(axis=1)).all()
        and (d.low <= d[["open", "close"]].min(axis=1)).all()
    )
    if not valid:
        raise ValueError(f"{market} source validation failed")
    d.index = t
    return d


def renewal_flags(close: np.ndarray) -> np.ndarray:
    prior_high = (
        pd.Series(close).shift(1).rolling(HIGH_WINDOW, min_periods=HIGH_WINDOW).max().to_numpy()
    )
    renew = np.zeros(len(close), dtype=bool)
    finite = np.isfinite(prior_high)
    renew[finite] = close[finite] > prior_high[finite]
    return renew


def positions(d: pd.DataFrame):
    close = d.close.to_numpy(float)
    renew = renewal_flags(close)
    p = {key: np.zeros(len(d) - 1) for key in ("candidate", "b1", "b0")}
    state = b1 = prev_base = 0.0
    onset_t: int | None = None
    downgraded = False
    regime_id = 0
    events: list[dict] = []

    for t in range(TREND, len(d) - 2):
        base = float(close[t] > close[t - TREND])
        p["b0"][t + 1] = base
        if d.index[t].hour == 0:
            event = {
                "decision_t": t,
                "execution_t": t + 1,
                "timestamp": d.index[t].isoformat(),
                "before": state,
                "after": None,
                "base": base,
                "onset": False,
                "downgrade": False,
                "base_exit": False,
                "regime_id": regime_id,
                "age_hours": None,
                "renewals_latest_168h": None,
                "drought168": None,
                "ret168": None,
            }
            if not base:
                if prev_base:
                    event["base_exit"] = True
                state = b1 = 0.0
                onset_t = None
                downgraded = False
            elif not prev_base:
                regime_id += 1
                state = b1 = 1.0
                onset_t = t
                downgraded = False
                event["onset"] = True
                event["regime_id"] = regime_id
                event["age_hours"] = 0
            else:
                b1 = 1.0
                event["regime_id"] = regime_id
                if onset_t is None:
                    raise ValueError("missing onset state")
                age = t - onset_t
                renewals = int(renew[t - DROUGHT + 1 : t + 1].sum())
                drought = renewals == 0
                ret168 = math.log(close[t] / close[t - RETURN_WINDOW])
                event["age_hours"] = age
                event["renewals_latest_168h"] = renewals
                event["drought168"] = drought
                event["ret168"] = ret168
                if not downgraded and age >= DROUGHT and drought and ret168 < 0:
                    state = 0.5
                    downgraded = True
                    event["downgrade"] = True
            event["after"] = state
            events.append(event)
            prev_base = base
        p["candidate"][t + 1], p["b1"][t + 1] = state, b1

    if not np.isin(p["candidate"], [0.0, 0.5, 1.0]).all():
        raise ValueError("candidate position domain")
    if np.any(p["candidate"] > p["b1"]):
        raise ValueError("candidate exceeds B1")
    return p, events, renew


def pack(d: pd.DataFrame, position: np.ndarray):
    open_ = d.open.to_numpy(float)
    market = open_[1:] / open_[:-1] - 1.0
    turnover = np.r_[abs(position[0]), abs(np.diff(position))]
    fees = FEE * turnover
    net = position * market - fees
    return market, turnover, fees, net


def sharpe(x: np.ndarray):
    sd = np.std(x, ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return None
    return float(math.sqrt(ANN) * np.mean(x) / sd)


def metrics(arrays, position: np.ndarray, span):
    _market, turnover, fees, net = arrays
    i, j = span
    n = net[i:j]
    wealth = np.cumprod(1.0 + n)
    path = np.r_[1.0, wealth]
    tv = float(turnover[i:j].sum())
    return {
        "net_return": float(wealth[-1] - 1.0),
        "arithmetic_net_return": float(n.sum()),
        "sharpe": sharpe(n),
        "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1.0)),
        "turnover": tv,
        "fees": float(fees[i:j].sum()),
        "edge_per_turnover_bps": float(n.sum() / tv * 1e4) if tv else None,
        "mean_exposure": float(position[i:j].mean()),
    }


def breadth(net: np.ndarray, index: pd.DatetimeIndex):
    folds = [
        float(np.prod(1.0 + net[OOS[0] + k * FOLD : OOS[0] + (k + 1) * FOLD]) - 1.0)
        for k in range(12)
    ]
    positive = [x for x in folds if x > 0]
    years = index[:-1].year[OOS[0] : OOS[1]]
    oos_net = net[OOS[0] : OOS[1]]
    year_returns = {
        str(y): float(np.prod(1.0 + oos_net[years == y]) - 1.0) for y in sorted(set(years))
    }
    return {
        "fold_returns": folds,
        "profitable_folds": sum(x > 0 for x in folds),
        "profitable_years": sum(x > 0 for x in year_returns.values()),
        "positive_fold_concentration": max(positive) / sum(positive) if positive else None,
        "year_returns": year_returns,
    }


def bootstrap(candidate: np.ndarray, benchmark: np.ndarray):
    c = candidate[OOS[0] : OOS[1]]
    b = benchmark[OOS[0] : OOS[1]]
    rng, n = np.random.default_rng(SEED), len(c)
    mean_delta = np.empty(RESAMPLES)
    sharpe_delta = np.empty(RESAMPLES)
    offsets = np.arange(BLOCK)
    n_blocks = math.ceil(n / BLOCK)
    for start in range(0, RESAMPLES, 100):
        q = min(100, RESAMPLES - start)
        block_starts = rng.integers(0, n - BLOCK + 1, (q, n_blocks))
        idx = (block_starts[:, :, None] + offsets).reshape(q, -1)[:, :n]
        cc, bb = c[idx], b[idx]
        cm, bm = cc.mean(axis=1), bb.mean(axis=1)
        cs, bs = cc.std(axis=1, ddof=1), bb.std(axis=1, ddof=1)
        mean_delta[start : start + q] = ANN * (cm - bm)
        csh = np.divide(math.sqrt(ANN) * cm, cs, out=np.zeros(q), where=cs > 0)
        bsh = np.divide(math.sqrt(ANN) * bm, bs, out=np.zeros(q), where=bs > 0)
        sharpe_delta[start : start + q] = csh - bsh
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
    }


def diagnose(d: pd.DataFrame, p, arrays, events, renew: np.ndarray):
    i, j = OOS
    candidate, b1 = p["candidate"], p["b1"]
    market, _, fees, net = arrays["candidate"]
    bnet = arrays["b1"][3]
    half = (candidate[i:j] == 0.5) & (b1[i:j] == 1.0)
    fee_delta = float(fees[i:j].sum() - arrays["b1"][2][i:j].sum())
    observed = float((net[i:j] - bnet[i:j]).sum())
    timing = float(((candidate[i:j] - b1[i:j]) * market[i:j]).sum())
    if not math.isclose(observed, timing - fee_delta, abs_tol=1e-12):
        raise ValueError("candidate-B1 decomposition")

    oos_events = [e for e in events if i <= e["execution_t"] < j]
    downgrades = [e for e in oos_events if e["downgrade"]]
    onsets = [e for e in oos_events if e["onset"]]
    base_exits = [e for e in oos_events if e["base_exit"]]

    forward: dict[str, dict] = {}
    for horizon in (24, 168, 720):
        values = []
        for event in downgrades:
            k = event["execution_t"]
            end = min(k + horizon, len(market))
            values.append(float(np.prod(1.0 + market[k:end]) - 1.0))
        forward[str(horizon)] = {
            "mean": float(np.mean(values)) if values else None,
            "median": float(np.median(values)) if values else None,
            "positive_share": float(np.mean(np.asarray(values) > 0)) if values else None,
        }

    # Repair the initial pooled attribution by separating carry before and after the
    # first subsequent hourly trailing-high renewal. The frozen policy does not restore
    # exposure, but this split diagnoses whether the drought warning remains useful
    # after the market causally demonstrates renewed strength.
    episodes = []
    for event in downgrades:
        start = event["execution_t"]
        next_exit = next(
            (x for x in events if x["base_exit"] and x["decision_t"] > event["decision_t"]),
            None,
        )
        end = next_exit["execution_t"] if next_exit is not None else len(candidate)
        end = min(end, j)
        if start >= end:
            continue
        renewal_candidates = np.flatnonzero(renew[event["decision_t"] + 1 : end])
        first_renewal_t = (
            int(event["decision_t"] + 1 + renewal_candidates[0])
            if renewal_candidates.size
            else None
        )
        split = min(first_renewal_t + 1, end) if first_renewal_t is not None else end
        pre_market = market[start:split]
        post_market = market[split:end]
        interval_market = market[start:end]
        if len(pre_market) + len(post_market) != end - start:
            raise ValueError("renewal split hours")
        if not math.isclose(
            float(pre_market.sum() + post_market.sum()),
            float(interval_market.sum()),
            abs_tol=1e-12,
        ):
            raise ValueError("renewal split carry")
        episodes.append(
            {
                "regime_id": event["regime_id"],
                "timestamp": event["timestamp"],
                "age_hours": event["age_hours"],
                "hours": int(end - start),
                "market_return_arithmetic": float(interval_market.sum()),
                "market_return_compounded": float(np.prod(1.0 + interval_market) - 1.0),
                "candidate_delta_before_fees": float(-0.5 * interval_market.sum()),
                "first_post_downgrade_renewal_timestamp": (
                    d.index[first_renewal_t].isoformat() if first_renewal_t is not None else None
                ),
                "hours_until_first_renewal_execution": int(split - start),
                "pre_renewal_hours": int(len(pre_market)),
                "pre_renewal_market_return_arithmetic": float(pre_market.sum()),
                "post_renewal_hours": int(len(post_market)),
                "post_renewal_market_return_arithmetic": float(post_market.sum()),
            }
        )

    attributed_hours = sum(x["hours"] for x in episodes)
    attributed_market = sum(x["market_return_arithmetic"] for x in episodes)
    pre_hours = sum(x["pre_renewal_hours"] for x in episodes)
    post_hours = sum(x["post_renewal_hours"] for x in episodes)
    pre_market = sum(x["pre_renewal_market_return_arithmetic"] for x in episodes)
    post_market = sum(x["post_renewal_market_return_arithmetic"] for x in episodes)
    if attributed_hours != int(half.sum()):
        raise ValueError("episode attribution hours")
    if not math.isclose(attributed_market, float(market[i:j][half].sum()), abs_tol=1e-12):
        raise ValueError("episode attribution carry")
    if pre_hours + post_hours != attributed_hours:
        raise ValueError("renewal aggregate hours")
    if not math.isclose(pre_market + post_market, attributed_market, abs_tol=1e-12):
        raise ValueError("renewal aggregate carry")

    eligible = [
        e
        for e in oos_events
        if e["base"]
        and e["age_hours"] is not None
        and e["age_hours"] >= DROUGHT
        and e["drought168"] is True
        and e["ret168"] is not None
        and e["ret168"] < 0
    ]

    return {
        "oos_onsets": len(onsets),
        "oos_base_exits": len(base_exits),
        "oos_downgrades": len(downgrades),
        "oos_eligible_drought_decisions": len(eligible),
        "oos_repeated_post_downgrade_eligible_decisions": len(eligible) - len(downgrades),
        "oos_hourly_renewals": int(renew[i:j].sum()),
        "half_state_hours": int(half.sum()),
        "full_exposure_equivalent_hours_removed": float(0.5 * half.sum()),
        "half_state_market_return_arithmetic": float(market[i:j][half].sum()),
        "market_carry_removed": float(0.5 * market[i:j][half].sum()),
        "incremental_fees": fee_delta,
        "arithmetic_net_delta": observed,
        "downgrade_forward_returns": forward,
        "episode_count": len(episodes),
        "episode_attributed_hours": attributed_hours,
        "episode_attributed_market_return": attributed_market,
        "renewal_split": {
            "pre_renewal_hours": int(pre_hours),
            "pre_renewal_market_return_arithmetic": float(pre_market),
            "post_renewal_hours": int(post_hours),
            "post_renewal_market_return_arithmetic": float(post_market),
            "post_renewal_share_of_half_state_hours": (
                float(post_hours / attributed_hours) if attributed_hours else None
            ),
            "post_renewal_share_of_positive_carry": (
                float(max(post_market, 0.0) / max(attributed_market, 0.0))
                if attributed_market > 0
                else None
            ),
        },
        "episode_duration_concentration": (
            max(x["hours"] for x in episodes) / attributed_hours if attributed_hours else None
        ),
    }


def run(d: pd.DataFrame):
    p, events, renew = positions(d)
    arrays = {key: pack(d, value) for key, value in p.items()}
    spans = (("training", TRAIN), ("development_oos", OOS), ("full_scored", FULL))
    met = {key: {name: metrics(arrays[key], p[key], span) for name, span in spans} for key in p}
    candidate_breadth = breadth(arrays["candidate"][3], d.index)
    b1_breadth = breadth(arrays["b1"][3], d.index)
    residual = arrays["candidate"][3][OOS[0] : OOS[1]] - arrays["b1"][3][OOS[0] : OOS[1]]
    boot = bootstrap(arrays["candidate"][3], arrays["b1"][3])
    candidate = met["candidate"]["development_oos"]
    b1 = met["b1"]["development_oos"]
    gates = {
        "candidate_oos_positive": candidate["net_return"] > 0,
        "oos_net_not_below_b1": candidate["net_return"] >= b1["net_return"],
        "oos_sharpe_not_below_b1": (
            candidate["sharpe"] is not None and candidate["sharpe"] >= b1["sharpe"]
        ),
        "oos_drawdown_not_worse_b1": candidate["max_drawdown"] >= b1["max_drawdown"],
        "oos_turnover_not_above_b1": candidate["turnover"] <= b1["turnover"],
        "oos_edge_per_turn_not_below_b1": (
            candidate["edge_per_turnover_bps"] >= b1["edge_per_turnover_bps"]
        ),
        "profitable_folds_at_least_7": candidate_breadth["profitable_folds"] >= 7,
        "profitable_years_at_least_3": candidate_breadth["profitable_years"] >= 3,
        "positive_fold_concentration_not_above_50pct": (
            candidate_breadth["positive_fold_concentration"] is not None
            and candidate_breadth["positive_fold_concentration"] <= 0.5
        ),
        "residual_sharpe_positive": (sharpe(residual) or 0.0) > 0,
        "mean_delta_lower_95_positive": boot["annualized_mean_delta"]["lower_95"] > 0,
        "sharpe_delta_lower_95_positive": boot["sharpe_delta"]["lower_95"] > 0,
        "full_scored_positive": met["candidate"]["full_scored"]["net_return"] > 0,
    }
    return {
        "metrics": met,
        "breadth": {
            "candidate": candidate_breadth,
            "b1": b1_breadth,
            "residual_sharpe_vs_b1": sharpe(residual),
        },
        "bootstrap": boot,
        "diagnostics": diagnose(d, p, arrays, events, renew),
        "acceptance_gates": gates,
        "accepted": all(gates.values()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc", type=Path, required=True)
    parser.add_argument("--eth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = {
        "family_id": "trend-renewal-drought-downgrade-1h-v1",
        "issue": 710,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "research_parent": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "source": {
            "provider": "OKX SPOT public confirmed 1H",
            "artifact_ids": {"BTC-USDT": 8704977298, "ETH-USDT": 8704978112},
            "hashes": HASHES,
            "rows_in_source": 43941,
            "scored_prefix_rows": N,
        },
        "sample": {
            "training": TRAIN,
            "development_oos": OOS,
            "full_scored": FULL,
            "later_suffix": [43440, 43941],
        },
        "rule": {
            "base": "close_t > close_(t-2160)",
            "renewal": "close_s > max(close_(s-720),...,close_(s-1))",
            "drought": "no renewal in completed hours [t-167,t]",
            "trigger": "age>=168 and drought and log(close_t/close_(t-168))<0",
            "state": "1.0 at onset; first trigger irreversibly downgrades to 0.5 until base exit",
        },
        "markets": {},
    }
    for market, path in (("BTC-USDT", args.btc), ("ETH-USDT", args.eth)):
        result["markets"][market] = run(load(path, market))
    result["accepted"] = all(value["accepted"] for value in result["markets"].values())
    result["verdict"] = (
        "nominate_exact_trend_renewal_drought_downgrade_for_replication"
        if result["accepted"]
        else "reject_exact_trend_renewal_drought_downgrade_family"
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(result["verdict"])


if __name__ == "__main__":
    main()
