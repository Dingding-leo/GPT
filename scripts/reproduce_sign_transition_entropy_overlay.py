from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE, ANN, TREND, EW, RW = 5e-4, 8760.0, 2160, 720, 168
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


def h2(p: float) -> float:
    if p <= 0 or p >= 1:
        return 0.0
    return -p * math.log2(p) - (1 - p) * math.log2(1 - p)


def entropy(s: np.ndarray) -> float:
    if len(s) != EW:
        raise ValueError("entropy block length")
    a, b = s[:-1], s[1:]
    n00, n01 = np.sum((a == 0) & (b == 0)), np.sum((a == 0) & (b == 1))
    n10, n11 = np.sum((a == 1) & (b == 0)), np.sum((a == 1) & (b == 1))
    if n00 + n01 + n10 + n11 != EW - 1:
        raise ValueError("transition identity")
    out = 0.0
    for x, y in ((n00, n01), (n10, n11)):
        row = x + y
        if row:
            out += row / (EW - 1) * h2(x / row)
    return float(out)


def positions(d: pd.DataFrame):
    c = d.close.to_numpy(float)
    s = np.zeros(len(d), np.int8)
    s[1:] = (np.diff(np.log(c)) > 0).astype(np.int8)
    p = {k: np.zeros(len(d) - 1) for k in ("candidate", "b1", "b0")}
    state = b1 = prev = 0.0
    events = []
    for t in range(TREND, len(d) - 2):
        base = float(c[t] > c[t - TREND])
        p["b0"][t + 1] = base
        if d.index[t].hour == 0:
            before = state
            risk = recovery = False
            hl = hp = r168 = None
            if not base:
                state = b1 = 0.0
            elif not prev:
                state = b1 = 1.0
            else:
                b1 = 1.0
                hl = entropy(s[t - EW + 1 : t + 1])
                hp = entropy(s[t - 2 * EW + 1 : t - EW + 1])
                r168 = math.log(c[t] / c[t - RW])
                risk = hl < hp and r168 < 0
                recovery = hl < hp and r168 > 0
                if risk:
                    state = 0.5
                elif recovery:
                    state = 1.0
            events.append((t + 1, before, state, risk, recovery, hl, hp, r168))
            prev = base
        p["candidate"][t + 1], p["b1"][t + 1] = state, b1
    if not np.isin(p["candidate"], [0, 0.5, 1]).all() or np.any(
        p["candidate"] > p["b1"]
    ):
        raise ValueError("position state")
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


def metrics(a, p, span):
    market, turn, fees, net = a
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


def breadth(net, index):
    folds = [
        float(
            np.prod(
                1 + net[OOS[0] + k * FOLD : OOS[0] + (k + 1) * FOLD]
            )
            - 1
        )
        for k in range(12)
    ]
    pos = [x for x in folds if x > 0]
    years = index[:-1].year[OOS[0] : OOS[1]]
    yn = net[OOS[0] : OOS[1]]
    yr = {
        str(y): float(np.prod(1 + yn[years == y]) - 1)
        for y in sorted(set(years))
    }
    return {
        "fold_returns": folds,
        "profitable_folds": sum(x > 0 for x in folds),
        "profitable_years": sum(x > 0 for x in yr.values()),
        "positive_fold_concentration": max(pos) / sum(pos) if pos else None,
        "year_returns": yr,
    }


def bootstrap(c, b):
    c, b = c[OOS[0] : OOS[1]], b[OOS[0] : OOS[1]]
    rng, n = np.random.default_rng(SEED), len(c)
    md, sd = np.empty(RESAMPLES), np.empty(RESAMPLES)
    offs, nb = np.arange(BLOCK), math.ceil(n / BLOCK)
    for z in range(0, RESAMPLES, 100):
        q = min(100, RESAMPLES - z)
        idx = (
            rng.integers(0, n - BLOCK + 1, (q, nb))[:, :, None] + offs
        ).reshape(q, -1)[:, :n]
        cc, bb = c[idx], b[idx]
        cm, bm = cc.mean(1), bb.mean(1)
        cs, bs = cc.std(1, ddof=1), bb.std(1, ddof=1)
        md[z : z + q] = ANN * (cm - bm)
        sd[z : z + q] = np.divide(
            math.sqrt(ANN) * cm, cs, out=np.zeros(q), where=cs > 0
        ) - np.divide(
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


def diagnose(p, arrays, events):
    i, j = OOS
    c, b = p["candidate"], p["b1"]
    market, _, fees, net = arrays["candidate"]
    selected = [x for x in events if i <= x[0] < j]
    risk = [x for x in selected if x[3]]
    recovery = [x for x in selected if x[4]]
    er = [x for x in risk if x[1] != x[2]]
    ec = [x for x in recovery if x[1] != x[2]]

    def fwd(rows):
        vals = []
        for x in rows:
            k = x[0]
            end = min(k + RW, len(market))
            vals.append(float(np.prod(1 + market[k:end]) - 1))
        return {
            "count": len(rows),
            "mean_next_168h": float(np.mean(vals)) if vals else None,
            "positive_next_168h_share": (
                float(np.mean(np.array(vals) > 0)) if vals else None
            ),
        }

    half = c[i:j] == 0.5
    carry = float(market[i:j][half].sum())
    fee_delta = float(fees[i:j].sum() - arrays["b1"][2][i:j].sum())
    observed = float((net[i:j] - arrays["b1"][3][i:j]).sum())
    timing = float(((c[i:j] - b[i:j]) * market[i:j]).sum())
    if not math.isclose(observed, timing - fee_delta, abs_tol=1e-12):
        raise ValueError("decomposition")
    return {
        "raw_risk_triggers": len(risk),
        "raw_recovery_triggers": len(recovery),
        "effective_risk_transitions": fwd(er),
        "effective_recovery_transitions": fwd(ec),
        "repeated_risk_triggers": len(risk) - len(er),
        "repeated_recovery_triggers": len(recovery) - len(ec),
        "half_state_hours": int(half.sum()),
        "half_state_market_return_arithmetic": carry,
        "full_exposure_equivalent_hours_removed": 0.5 * int(half.sum()),
        "market_carry_removed": 0.5 * carry,
        "incremental_fees": fee_delta,
        "arithmetic_net_delta": observed,
    }


def run(d):
    p, events = positions(d)
    arrays = {k: pack(d, v) for k, v in p.items()}
    spans = (("training", TRAIN), ("development_oos", OOS), ("full_scored", FULL))
    met = {
        key: {name: metrics(arrays[key], p[key], span) for name, span in spans}
        for key in p
    }
    cb = breadth(arrays["candidate"][3], d.index)
    bb = breadth(arrays["b1"][3], d.index)
    residual = (
        arrays["candidate"][3][OOS[0] : OOS[1]]
        - arrays["b1"][3][OOS[0] : OOS[1]]
    )
    boot = bootstrap(arrays["candidate"][3], arrays["b1"][3])
    c, b = met["candidate"]["development_oos"], met["b1"]["development_oos"]
    gates = {
        "candidate_oos_positive": c["net_return"] > 0,
        "oos_net_not_below_b1": c["net_return"] >= b["net_return"],
        "oos_sharpe_not_below_b1": (
            c["sharpe"] is not None and c["sharpe"] >= b["sharpe"]
        ),
        "oos_drawdown_not_worse_b1": c["max_drawdown"] >= b["max_drawdown"],
        "oos_turnover_not_above_b1": c["turnover"] <= b["turnover"],
        "oos_edge_per_turn_not_below_b1": (
            c["edge_per_turnover_bps"] >= b["edge_per_turnover_bps"]
        ),
        "profitable_folds_at_least_7": cb["profitable_folds"] >= 7,
        "profitable_years_at_least_3": cb["profitable_years"] >= 3,
        "positive_fold_concentration_not_above_50pct": (
            cb["positive_fold_concentration"] is not None
            and cb["positive_fold_concentration"] <= 0.5
        ),
        "residual_sharpe_positive": (sharpe(residual) or 0) > 0,
        "mean_delta_lower_95_positive": (
            boot["annualized_mean_delta"]["lower_95"] > 0
        ),
        "sharpe_delta_lower_95_positive": (
            boot["sharpe_delta"]["lower_95"] > 0
        ),
    }
    return {
        "metrics": met,
        "breadth": {
            "candidate": cb,
            "b1": bb,
            "residual_sharpe_vs_b1": sharpe(residual),
        },
        "bootstrap": boot,
        "diagnostics": diagnose(p, arrays, events),
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
        "family_id": "sign-transition-entropy-persistence-overlay-1h-v1",
        "issue": 705,
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
        "sample": {
            "training": TRAIN,
            "development_oos": OOS,
            "full_scored": FULL,
        },
        "markets": {},
    }
    for m, path in (("BTC-USDT", a.btc), ("ETH-USDT", a.eth)):
        out["markets"][m] = run(load(path, m))
    out["accepted"] = all(v["accepted"] for v in out["markets"].values())
    out["verdict"] = (
        "nominate_exact_sign_transition_entropy_persistence_overlay_for_replication"
        if out["accepted"]
        else "reject_exact_sign_transition_entropy_persistence_overlay_family"
    )
    a.output.write_text(json.dumps(out, sort_keys=True, indent=2) + "\n")
    print(out["verdict"])

if __name__ == "__main__":
    main()
