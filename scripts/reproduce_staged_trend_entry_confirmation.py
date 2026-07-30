from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE, ANN, TREND, RW = 5e-4, 8760.0, 2160, 168
N, FOLD, BLOCK, RESAMPLES, SEED = 43441, 2160, 168, 5000, 20260730
TRAIN, OOS, FULL = (2880, 17520), (17520, 43440), (2880, 43440)
HASHES = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path, market: str) -> pd.DataFrame:
    if sha(path) != HASHES[market]:
        raise ValueError(f"{market} hash mismatch")
    d = pd.read_csv(path, nrows=N)
    t = pd.DatetimeIndex(pd.to_datetime(d.timestamp, utc=True))
    num = d[["open", "high", "low", "close", "volume_quote"]].to_numpy(float)
    ok = (
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
    if not ok:
        raise ValueError(f"{market} source validation failed")
    d.index = t
    return d


def positions(d: pd.DataFrame):
    c = d.close.to_numpy(float)
    p = {k: np.zeros(len(d) - 1) for k in ("candidate", "b1", "b0")}
    state = b1 = prev_base = 0.0
    onset_t = None
    onset_close = None
    events: list[dict] = []
    regime_id = 0

    for t in range(TREND, len(d) - 2):
        base = float(c[t] > c[t - TREND])
        p["b0"][t + 1] = base
        if d.index[t].hour == 0:
            before = state
            event = {
                "decision_t": t,
                "execution_t": t + 1,
                "timestamp": d.index[t].isoformat(),
                "before": before,
                "after": None,
                "base": base,
                "onset": False,
                "topup": False,
                "base_exit": False,
                "regime_id": regime_id,
                "age_hours": None,
                "ret_onset": None,
                "ret168": None,
            }
            if not base:
                if prev_base:
                    event["base_exit"] = True
                state = b1 = 0.0
                onset_t = None
                onset_close = None
            elif not prev_base:
                regime_id += 1
                state, b1 = 0.5, 1.0
                onset_t, onset_close = t, c[t]
                event["onset"] = True
                event["regime_id"] = regime_id
                event["age_hours"] = 0
                event["ret_onset"] = 0.0
                event["ret168"] = math.log(c[t] / c[t - RW])
            else:
                b1 = 1.0
                event["regime_id"] = regime_id
                if onset_t is None or onset_close is None:
                    raise ValueError("missing onset state")
                age = t - onset_t
                ret_onset = math.log(c[t] / onset_close)
                ret168 = math.log(c[t] / c[t - RW])
                event["age_hours"] = age
                event["ret_onset"] = ret_onset
                event["ret168"] = ret168
                if state == 0.5 and age >= RW and ret_onset > 0 and ret168 > 0:
                    state = 1.0
                    event["topup"] = True
            event["after"] = state
            events.append(event)
            prev_base = base
        p["candidate"][t + 1], p["b1"][t + 1] = state, b1

    if not np.isin(p["candidate"], [0, 0.5, 1]).all():
        raise ValueError("candidate position domain")
    if np.any(p["candidate"] > p["b1"]):
        raise ValueError("candidate exceeds B1")
    return p, events


def pack(d: pd.DataFrame, p: np.ndarray):
    o = d.open.to_numpy(float)
    market = o[1:] / o[:-1] - 1
    turn = np.r_[abs(p[0]), abs(np.diff(p))]
    fees = FEE * turn
    net = p * market - fees
    return market, turn, fees, net


def sharpe(x):
    sd = np.std(x, ddof=1)
    if not np.isfinite(sd) or sd <= 0:
        return None
    return float(math.sqrt(ANN) * np.mean(x) / sd)


def metrics(a, p: np.ndarray, span):
    _market, turn, fees, net = a
    i, j = span
    n = net[i:j]
    wealth = np.cumprod(1 + n)
    path = np.r_[1.0, wealth]
    tv = float(turn[i:j].sum())
    return {
        "net_return": float(wealth[-1] - 1),
        "sharpe": sharpe(n),
        "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1)),
        "turnover": tv,
        "fees": float(fees[i:j].sum()),
        "edge_per_turnover_bps": float(n.sum() / tv * 1e4) if tv else None,
        "mean_exposure": float(p[i:j].mean()),
    }


def breadth(net: np.ndarray, index: pd.DatetimeIndex):
    folds = [
        float(np.prod(1 + net[OOS[0] + k * FOLD : OOS[0] + (k + 1) * FOLD]) - 1)
        for k in range(12)
    ]
    pos = [x for x in folds if x > 0]
    years = index[:-1].year[OOS[0] : OOS[1]]
    yn = net[OOS[0] : OOS[1]]
    yr = {str(y): float(np.prod(1 + yn[years == y]) - 1) for y in sorted(set(years))}
    return {
        "fold_returns": folds,
        "profitable_folds": sum(x > 0 for x in folds),
        "profitable_years": sum(x > 0 for x in yr.values()),
        "positive_fold_concentration": max(pos) / sum(pos) if pos else None,
        "year_returns": yr,
    }


def bootstrap(c: np.ndarray, b: np.ndarray):
    c, b = c[OOS[0] : OOS[1]], b[OOS[0] : OOS[1]]
    rng, n = np.random.default_rng(SEED), len(c)
    md, sd = np.empty(RESAMPLES), np.empty(RESAMPLES)
    offs, nb = np.arange(BLOCK), math.ceil(n / BLOCK)
    for z in range(0, RESAMPLES, 100):
        q = min(100, RESAMPLES - z)
        idx = (rng.integers(0, n - BLOCK + 1, (q, nb))[:, :, None] + offs).reshape(q, -1)[:, :n]
        cc, bb = c[idx], b[idx]
        cm, bm = cc.mean(1), bb.mean(1)
        cs, bs = cc.std(1, ddof=1), bb.std(1, ddof=1)
        md[z : z + q] = ANN * (cm - bm)
        sd[z : z + q] = np.divide(math.sqrt(ANN) * cm, cs, out=np.zeros(q), where=cs > 0) - np.divide(
            math.sqrt(ANN) * bm, bs, out=np.zeros(q), where=bs > 0
        )
    return {
        "annualized_mean_delta": {
            "point": float(ANN * np.mean(c - b)),
            "lower_95": float(np.quantile(md, 0.025)),
            "upper_95": float(np.quantile(md, 0.975)),
        },
        "sharpe_delta": {
            "point": float((sharpe(c) or 0) - (sharpe(b) or 0)),
            "lower_95": float(np.quantile(sd, 0.025)),
            "upper_95": float(np.quantile(sd, 0.975)),
        },
    }


def diagnose(d: pd.DataFrame, p, arrays, events):
    i, j = OOS
    candidate, b1 = p["candidate"], p["b1"]
    market, _, fees, net = arrays["candidate"]
    bnet = arrays["b1"][3]
    half = candidate[i:j] == 0.5
    fee_delta = float(fees[i:j].sum() - arrays["b1"][2][i:j].sum())
    observed = float((net[i:j] - bnet[i:j]).sum())
    timing = float(((candidate[i:j] - b1[i:j]) * market[i:j]).sum())
    if not math.isclose(observed, timing - fee_delta, abs_tol=1e-12):
        raise ValueError("decomposition")

    oos_events = [e for e in events if i <= e["execution_t"] < j]
    onsets = [e for e in oos_events if e["onset"]]
    topups = [e for e in oos_events if e["topup"]]

    regime_summaries = []
    daily = [e for e in events if e["regime_id"] > 0]
    ids = sorted({e["regime_id"] for e in daily})
    for rid in ids:
        es = [e for e in daily if e["regime_id"] == rid]
        onset = next((e for e in es if e["onset"]), None)
        if onset is None:
            continue
        start = onset["execution_t"]
        exit_event = next((e for e in events if e["base_exit"] and e["decision_t"] > onset["decision_t"]), None)
        end = exit_event["execution_t"] if exit_event else len(candidate)
        top = next((e for e in es if e["topup"]), None)
        overlap_start, overlap_end = max(start, i), min(end, j)
        if overlap_start >= overlap_end:
            continue
        half_mask = candidate[overlap_start:overlap_end] == 0.5
        m = market[overlap_start:overlap_end]
        regime_summaries.append(
            {
                "regime_id": rid,
                "onset_timestamp": onset["timestamp"],
                "started_in_oos": bool(i <= start < j),
                "overlap_hours": int(overlap_end - overlap_start),
                "half_hours": int(half_mask.sum()),
                "topup_timestamp": top["timestamp"] if top else None,
                "topup_delay_hours": int(top["age_hours"]) if top else None,
                "market_return_during_half_arithmetic": float(m[half_mask].sum()),
                "market_return_full_overlap_compounded": float(np.prod(1 + m) - 1),
            }
        )

    topup_forward = []
    for e in topups:
        k = e["execution_t"]
        for h in (24, 168, 720):
            end = min(k + h, len(market))
            topup_forward.append((h, float(np.prod(1 + market[k:end]) - 1)))
    fwd = {}
    for h in (24, 168, 720):
        vals = [v for hh, v in topup_forward if hh == h]
        fwd[str(h)] = {
            "mean": float(np.mean(vals)) if vals else None,
            "positive_share": float(np.mean(np.array(vals) > 0)) if vals else None,
        }

    if arrays["candidate"][1][i:j].sum() > arrays["b1"][1][i:j].sum() + 1e-12:
        raise ValueError("turnover monotonicity")

    confirmed = [r for r in regime_summaries if r["topup_timestamp"] is not None]
    unconfirmed = [r for r in regime_summaries if r["topup_timestamp"] is None]

    def stage_group(rows):
        hours = sum(r["half_hours"] for r in rows)
        carry = sum(r["market_return_during_half_arithmetic"] for r in rows)
        return {
            "regimes": len(rows),
            "half_hours": int(hours),
            "half_state_market_return_arithmetic": float(carry),
            "candidate_delta_from_half_sizing_before_fees": float(-0.5 * carry),
        }

    cg, ug = stage_group(confirmed), stage_group(unconfirmed)
    if cg["half_hours"] + ug["half_hours"] != int(half.sum()):
        raise ValueError("stage attribution hours")
    if not math.isclose(
        cg["half_state_market_return_arithmetic"] + ug["half_state_market_return_arithmetic"],
        float(market[i:j][half].sum()),
        abs_tol=1e-12,
    ):
        raise ValueError("stage attribution carry")
    attributed = (
        cg["candidate_delta_from_half_sizing_before_fees"]
        + ug["candidate_delta_from_half_sizing_before_fees"]
        - fee_delta
    )
    if not math.isclose(attributed, observed, abs_tol=1e-12):
        raise ValueError("stage attribution net")

    return {
        "oos_onsets": len(onsets),
        "oos_topups": len(topups),
        "oos_unconfirmed_started_regimes": sum(
            r["started_in_oos"] and r["topup_timestamp"] is None for r in regime_summaries
        ),
        "half_state_hours": int(half.sum()),
        "full_exposure_equivalent_hours_removed": 0.5 * int(half.sum()),
        "half_state_market_return_arithmetic": float(market[i:j][half].sum()),
        "market_carry_removed": float(0.5 * market[i:j][half].sum()),
        "incremental_fees": fee_delta,
        "arithmetic_net_delta": observed,
        "confirmed_regime_half_stage": cg,
        "unconfirmed_regime_half_stage": ug,
        "topup_forward_returns": fwd,
        "regimes": regime_summaries,
    }


def run(d: pd.DataFrame):
    p, events = positions(d)
    arrays = {k: pack(d, v) for k, v in p.items()}
    spans = (("training", TRAIN), ("development_oos", OOS), ("full_scored", FULL))
    met = {key: {name: metrics(arrays[key], p[key], span) for name, span in spans} for key in p}
    cb = breadth(arrays["candidate"][3], d.index)
    bb = breadth(arrays["b1"][3], d.index)
    residual = arrays["candidate"][3][OOS[0] : OOS[1]] - arrays["b1"][3][OOS[0] : OOS[1]]
    boot = bootstrap(arrays["candidate"][3], arrays["b1"][3])
    c, b = met["candidate"]["development_oos"], met["b1"]["development_oos"]
    gates = {
        "candidate_oos_positive": c["net_return"] > 0,
        "oos_net_not_below_b1": c["net_return"] >= b["net_return"],
        "oos_sharpe_not_below_b1": c["sharpe"] is not None and c["sharpe"] >= b["sharpe"],
        "oos_drawdown_not_worse_b1": c["max_drawdown"] >= b["max_drawdown"],
        "oos_turnover_not_above_b1": c["turnover"] <= b["turnover"],
        "oos_edge_per_turn_not_below_b1": c["edge_per_turnover_bps"] >= b["edge_per_turnover_bps"],
        "profitable_folds_at_least_7": cb["profitable_folds"] >= 7,
        "profitable_years_at_least_3": cb["profitable_years"] >= 3,
        "positive_fold_concentration_not_above_50pct": cb["positive_fold_concentration"] is not None
        and cb["positive_fold_concentration"] <= 0.5,
        "residual_sharpe_positive": (sharpe(residual) or 0) > 0,
        "mean_delta_lower_95_positive": boot["annualized_mean_delta"]["lower_95"] > 0,
        "sharpe_delta_lower_95_positive": boot["sharpe_delta"]["lower_95"] > 0,
        "full_scored_positive": met["candidate"]["full_scored"]["net_return"] > 0,
    }
    return {
        "metrics": met,
        "breadth": {"candidate": cb, "b1": bb, "residual_sharpe_vs_b1": sharpe(residual)},
        "bootstrap": boot,
        "diagnostics": diagnose(d, p, arrays, events),
        "acceptance_gates": gates,
        "accepted": all(gates.values()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--btc", type=Path, required=True)
    ap.add_argument("--eth", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    out = {
        "family_id": "staged-trend-entry-confirmation-sizing-1h-v1",
        "issue": 707,
        "candidate_count": 1,
        "parameter_grid_count": 0,
        "fee_one_way": FEE,
        "research_parent": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "source": {
            "provider": "OKX SPOT public confirmed 1H",
            "hashes": HASHES,
            "rows_in_source": 43941,
            "scored_prefix_rows": N,
        },
        "sample": {"training": TRAIN, "development_oos": OOS, "full_scored": FULL},
        "markets": {},
    }
    for m, path in (("BTC-USDT", a.btc), ("ETH-USDT", a.eth)):
        out["markets"][m] = run(load(path, m))
    out["accepted"] = all(v["accepted"] for v in out["markets"].values())
    out["verdict"] = (
        "nominate_exact_staged_trend_entry_confirmation_sizing_for_replication"
        if out["accepted"]
        else "reject_exact_staged_trend_entry_confirmation_sizing_family"
    )
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(out, sort_keys=True, indent=2) + "\n")
    print(out["verdict"])


if __name__ == "__main__":
    main()
