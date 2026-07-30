# ruff: noqa
# fmt: off
from __future__ import annotations
import argparse, hashlib, json, math
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

FEE = 0.0005
ANN = 8760.0
W = 2160
LONG_H = 720
SHORT_H = 168
N = 43441
FOLD = 2160
TRAIN = (2880, 17520)
OOS = (17520, 43440)
FULL = (2880, 43440)
SEED = 20260730
ISSUE = 667
FAMILY = "downside-semivariance-persistence-risk-state-1h-v1"
HASH = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}
ART = {"BTC-USDT": 8704977298, "ETH-USDT": 8704978112}


def native(x: Any) -> Any:
    if isinstance(x, dict): return {str(k): native(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [native(v) for v in x]
    if isinstance(x, np.generic): return x.item()
    return x


def load(path: Path, market: str) -> pd.DataFrame:
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != HASH[market]: raise ValueError(f"{market} hash mismatch: {digest}")
    d = pd.read_csv(path, nrows=N)
    t = pd.DatetimeIndex(pd.to_datetime(d.timestamp, utc=True))
    x = d[["open", "high", "low", "close", "volume_quote"]].to_numpy(float)
    ok = (
        len(d) == N
        and t.equals(pd.date_range(t[0], periods=len(t), freq="1h", tz="UTC"))
        and t.is_unique
        and (d.confirm == 1).all()
        and np.isfinite(x).all()
        and (x[:, :4] > 0).all()
        and (x[:, 4] >= 0).all()
        and (d.high >= d.low).all()
    )
    if not ok: raise ValueError(f"{market} source validation failed")
    d.index = t
    return d


def rolling_sum(x: np.ndarray, h: int) -> np.ndarray:
    cs = np.r_[0.0, np.cumsum(x)]
    out = np.full(len(x), np.nan)
    idx = np.arange(h, len(x))
    out[idx] = cs[idx + 1] - cs[idx + 1 - h]
    return out


def features(d: pd.DataFrame) -> dict[str, np.ndarray]:
    c = d.close.to_numpy(float)
    n = len(c)
    r = np.zeros(n)
    r[1:] = np.diff(np.log(c))
    downside = np.minimum(r, 0.0) ** 2
    upside = np.maximum(r, 0.0) ** 2
    d720 = rolling_sum(downside, LONG_H)
    u720 = rolling_sum(upside, LONG_H)
    d168 = rolling_sum(downside, SHORT_H)
    u168 = rolling_sum(upside, SHORT_H)
    d168_prior = np.full(n, np.nan)
    u168_prior = np.full(n, np.nan)
    d168_prior[SHORT_H:] = d168[:-SHORT_H]
    u168_prior[SHORT_H:] = u168[:-SHORT_H]
    def share(dd: np.ndarray, uu: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        den = dd + uu
        valid = np.isfinite(dd) & np.isfinite(uu) & (den > 0)
        s = np.full(n, 0.5)
        s[valid] = dd[valid] / den[valid]
        return s, valid
    s720, v720 = share(d720, u720)
    s168, v168 = share(d168, u168)
    s168p, v168p = share(d168_prior, u168_prior)
    valid = v720 & v168 & v168p
    trigger = valid & (d720 > u720) & (s168 > s168p)
    clear = valid & (d720 <= u720) & (s168 <= s168p)
    margin = np.full(n, np.nan)
    margin[W:] = np.log(c[W:] / c[:-W])
    return {
        "returns": r, "downside_sq": downside, "upside_sq": upside,
        "d720": d720, "u720": u720, "s720": s720,
        "s168_recent": s168, "s168_prior": s168p,
        "valid": valid, "risk_trigger": trigger, "risk_clear": clear,
        "slow_margin": margin,
    }


def positions(d: pd.DataFrame, f: dict[str, np.ndarray]) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    n = len(d)
    out = {k: np.zeros(n - 1) for k in ("candidate", "b0", "b1")}
    cand = b0 = b1 = 0.0
    rec: list[dict[str, Any]] = []
    for t in range(W, n - 1):
        base = bool(f["slow_margin"][t] > 0)
        b0 = float(base)
        if d.index[t].hour == 0:
            prev = cand
            trig = bool(f["risk_trigger"][t])
            clr = bool(f["risk_clear"][t])
            if not base:
                cand = 0.0
                reason = "slow_trend_exit" if prev != 0 else "cash_base_nonpositive"
            elif prev == 0.0:
                cand = 0.5 if trig else 1.0
                reason = "entry_half_triggered" if trig else "entry_full"
            elif prev == 1.0:
                cand = 0.5 if trig else 1.0
                reason = "full_to_half_trigger" if trig else "hold_full"
            elif prev == 0.5:
                cand = 1.0 if clr else 0.5
                reason = "half_to_full_clear" if clr else "hold_half"
            else:
                raise ValueError("invalid candidate state")
            b1 = float(base)
            rec.append({
                "t": t, "execution_index": t + 1, "timestamp": d.index[t].isoformat(), "base_positive": base,
                "d720": float(f["d720"][t]), "u720": float(f["u720"][t]),
                "s720": float(f["s720"][t]), "s168_recent": float(f["s168_recent"][t]),
                "s168_prior": float(f["s168_prior"][t]), "valid": bool(f["valid"][t]),
                "risk_trigger": trig, "risk_clear": clr, "previous_target": float(prev),
                "target": float(cand), "reason": reason,
            })
        j = t + 1
        if j < n - 1:
            out["candidate"][j] = cand
            out["b0"][j] = b0
            out["b1"][j] = b1
    vals = set(np.unique(out["candidate"]).tolist())
    if not vals.issubset({0.0, 0.5, 1.0}): raise ValueError(f"candidate states {vals}")
    if np.any(out["candidate"] - out["b1"] > 1e-15): raise ValueError("candidate exceeds B1")
    for key in ("candidate", "b1"):
        z = np.flatnonzero(np.r_[out[key][0] != 0, np.diff(out[key]) != 0])
        if any(i <= 0 or d.index[int(i) - 1].hour != 0 for i in z): raise ValueError(f"{key} next-open timing")
    return out, rec


def pack(d: pd.DataFrame, p: np.ndarray) -> dict[str, np.ndarray]:
    o = d.open.to_numpy(float)
    market = o[1:] / o[:-1] - 1.0
    turn = np.r_[abs(p[0]), np.abs(np.diff(p))]
    fees = FEE * turn
    net = p * market - fees
    if not np.array_equal(net, p * market - FEE * turn): raise ValueError("fee identity")
    return {"market": market, "turn": turn, "fees": fees, "net": net}


def sharpe(x: np.ndarray) -> float | None:
    s = float(np.std(x, ddof=1))
    return None if not np.isfinite(s) or s <= 0 else float(math.sqrt(ANN) * np.mean(x) / s)


def metric(a: dict[str, np.ndarray], p: np.ndarray, span: tuple[int, int]) -> dict[str, Any]:
    s, e = span
    n = a["net"][s:e]
    x = p[s:e]
    wealth = np.cumprod(1.0 + n)
    path = np.r_[1.0, wealth]
    turn = float(a["turn"][s:e].sum())
    prev = np.r_[p[s - 1] if s else 0.0, x[:-1]]
    ex = n[x > 0]
    longest = cur = 0
    for v in ex < 0:
        cur = cur + 1 if v else 0
        longest = max(longest, cur)
    return {
        "net_return": float(wealth[-1] - 1.0), "arithmetic_net_return": float(n.sum()),
        "sharpe": sharpe(n), "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1.0)),
        "turnover": turn, "exposure_change_count": int((np.abs(x - prev) > 1e-15).sum()),
        "fees": float(a["fees"][s:e].sum()),
        "edge_per_turnover_bps": float(n.sum() / turn * 1e4) if turn else None,
        "mean_exposure": float(x.mean()), "exposed_hours": int((x > 0).sum()),
        "half_exposure_hours": int((x == 0.5).sum()), "full_exposure_hours": int((x == 1.0).sum()),
        "loss_hour_rate_when_exposed": float(np.mean(ex < 0)) if len(ex) else None,
        "longest_exposed_loss_cluster_hours": int(longest),
    }


def breadth(net: np.ndarray, timestamps: pd.DatetimeIndex) -> dict[str, Any]:
    fold_returns = [float(np.prod(1 + net[OOS[0] + k * FOLD: OOS[0] + (k + 1) * FOLD]) - 1) for k in range(12)]
    positive = [x for x in fold_returns if x > 0]
    years = timestamps[:-1].year
    yr: dict[str, float] = {}
    for y in sorted(set(years[OOS[0]:OOS[1]])):
        mask = years[OOS[0]:OOS[1]] == y
        yr[str(y)] = float(np.prod(1 + net[OOS[0]:OOS[1]][mask]) - 1)
    return {
        "fold_returns": fold_returns, "profitable_folds": int(sum(x > 0 for x in fold_returns)),
        "year_returns": yr, "profitable_years": int(sum(x > 0 for x in yr.values())),
        "positive_fold_concentration": float(max(positive) / sum(positive)) if positive else None,
    }


def bootstrap(c: np.ndarray, b: np.ndarray) -> dict[str, Any]:
    c = c[OOS[0]:OOS[1]]; b = b[OOS[0]:OOS[1]]
    n = len(c); rng = np.random.default_rng(SEED)
    mean_delta = np.empty(5000); sharpe_delta = np.empty(5000)
    off = np.arange(168); blocks = math.ceil(n / 168)
    for q in range(0, 5000, 100):
        e = q + 100
        starts = rng.integers(0, n - 167, size=(100, blocks))
        idx = (starts[:, :, None] + off).reshape(100, -1)[:, :n]
        cs = c[idx]; bs = b[idx]
        cm = cs.mean(1); bm = bs.mean(1)
        cstd = cs.std(1, ddof=1); bstd = bs.std(1, ddof=1)
        mean_delta[q:e] = ANN * (cm - bm)
        sharpe_delta[q:e] = (
            np.divide(math.sqrt(ANN) * cm, cstd, out=np.zeros(100), where=cstd > 0)
            - np.divide(math.sqrt(ANN) * bm, bstd, out=np.zeros(100), where=bstd > 0)
        )
    return {
        "annualized_mean_delta": {"point": float(ANN * np.mean(c - b)), "lower_95": float(np.quantile(mean_delta, .025)), "upper_95": float(np.quantile(mean_delta, .975))},
        "sharpe_delta": {"point": float((sharpe(c) or 0) - (sharpe(b) or 0)), "lower_95": float(np.quantile(sharpe_delta, .025)), "upper_95": float(np.quantile(sharpe_delta, .975))},
        "block_hours": 168, "resamples": 5000, "seed": SEED,
    }


def qdict(x: np.ndarray) -> dict[str, float]:
    return {str(q): float(np.quantile(x, q)) for q in (0, .1, .25, .5, .75, .9, 1)}


def feature_diag(rec: list[dict[str, Any]], span: tuple[int, int]) -> dict[str, Any]:
    rr = [r for r in rec if span[0] <= r["t"] < span[1]]
    if not rr: return {}
    pos = [r for r in rr if r["base_positive"]]
    def arr(key: str) -> np.ndarray: return np.array([r[key] for r in rr], float)
    ratios = np.divide(arr("d720"), arr("u720"), out=np.full(len(rr), np.nan), where=arr("u720") > 0)
    trans: dict[str, int] = {}
    for r in rr: trans[r["reason"]] = trans.get(r["reason"], 0) + 1
    return {
        "daily_decisions": len(rr), "positive_base_decisions": len(pos),
        "valid_feature_decisions": int(sum(r["valid"] for r in rr)),
        "risk_trigger_decisions": int(sum(r["risk_trigger"] for r in rr)),
        "risk_clear_decisions": int(sum(r["risk_clear"] for r in rr)),
        "risk_trigger_rate": float(np.mean([r["risk_trigger"] for r in rr])),
        "risk_trigger_rate_positive_base": float(np.mean([r["risk_trigger"] for r in pos])) if pos else None,
        "d720_u720_ratio_quantiles": qdict(ratios[np.isfinite(ratios)]),
        "s720_quantiles": qdict(arr("s720")),
        "s168_recent_quantiles": qdict(arr("s168_recent")),
        "s168_prior_quantiles": qdict(arr("s168_prior")),
        "share_change_quantiles": qdict(arr("s168_recent") - arr("s168_prior")),
        "decision_reasons": trans,
    }


def state_contrib(pos: np.ndarray, a: dict[str, np.ndarray], span: tuple[int, int]) -> dict[str, Any]:
    s, e = span; p = pos[s:e]; m = a["market"][s:e]; fees = a["fees"][s:e]; net = a["net"][s:e]
    out = {}
    for state in (0.0, 0.5, 1.0):
        z = p == state
        out[str(state)] = {
            "hours": int(z.sum()), "market_arithmetic_contribution": float((p[z] * m[z]).sum()),
            "fees": float(fees[z].sum()), "net_arithmetic_contribution": float(net[z].sum()),
            "mean_market_return": float(m[z].mean()) if z.any() else None,
        }
    return out


def transition_diag(rec: list[dict[str, Any]], span: tuple[int, int]) -> dict[str, Any]:
    rr = [r for r in rec if span[0] <= r["execution_index"] < span[1] and r["target"] != r["previous_target"]]
    out: dict[str, Any] = {}
    total = 0.0
    for r in rr:
        key = f"{r['previous_target']:g}->{r['target']:g}:{r['reason']}"
        out.setdefault(key, {"count": 0, "turnover": 0.0, "fees": 0.0})
        delta = abs(r["target"] - r["previous_target"])
        out[key]["count"] += 1; out[key]["turnover"] += delta; out[key]["fees"] += FEE * delta; total += delta
    return {"by_transition": out, "total_decision_turnover": total, "total_decision_fees": FEE * total}


def forward_diag(rec: list[dict[str, Any]], market: np.ndarray, span: tuple[int, int]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for label, pred in (("risk_trigger", lambda r: r["risk_trigger"]), ("risk_clear", lambda r: r["risk_clear"])):
        rows = [r for r in rec if span[0] <= r["t"] < span[1] and r["base_positive"] and pred(r)]
        d: dict[str, Any] = {"events": len(rows)}
        for h in (24, 168):
            vals = []
            for r in rows:
                start = r["t"] + 1
                end = start + h
                if end <= span[1] and end <= len(market): vals.append(float(np.prod(1 + market[start:end]) - 1))
            d[f"forward_{h}h"] = {
                "complete_events": len(vals), "mean": float(np.mean(vals)) if vals else None,
                "median": float(np.median(vals)) if vals else None, "positive_rate": float(np.mean(np.array(vals) > 0)) if vals else None,
            }
        out[label] = d
    return out


def selector_diag(rec: list[dict[str, Any]], pos: dict[str, np.ndarray], a: dict[str, dict[str, np.ndarray]]) -> dict[str, Any]:
    s, e = OOS; c = pos["candidate"][s:e]; b = pos["b1"][s:e]; m = a["candidate"]["market"][s:e]
    more = c > b + 1e-15; less = b > c + 1e-15
    fee_delta = float(a["candidate"]["fees"][s:e].sum() - a["b1"]["fees"][s:e].sum())
    observed = float(a["candidate"]["net"][s:e].sum() - a["b1"]["net"][s:e].sum())
    exposure_market = float(((c - b) * m).sum())
    reconstructed = exposure_market - fee_delta
    if not math.isclose(observed, reconstructed, abs_tol=1e-12): raise ValueError("decomposition")
    trans = transition_diag(rec, OOS)
    if not math.isclose(trans["total_decision_turnover"], float(a["candidate"]["turn"][s:e].sum()), abs_tol=1e-12):
        raise ValueError(f"transition turnover reconstruction {trans['total_decision_turnover']} vs {a['candidate']['turn'][s:e].sum()}")
    cn = a["candidate"]["net"][s:e]; bn = a["b1"]["net"][s:e]
    return {
        "oos_exposure_decomposition": {
            "candidate_more_hours": int(more.sum()), "candidate_more_exposure_hours": float(np.maximum(c - b, 0).sum()),
            "candidate_less_hours": int(less.sum()), "candidate_less_exposure_hours": float(np.maximum(b - c, 0).sum()),
            "exposure_delta_market_arithmetic_return": exposure_market,
            "candidate_fees": float(a["candidate"]["fees"][s:e].sum()), "b1_fees": float(a["b1"]["fees"][s:e].sum()),
            "incremental_fees_candidate_minus_b1": fee_delta,
            "observed_candidate_minus_b1_arithmetic_net": observed,
            "reconstructed_candidate_minus_b1_arithmetic_net": reconstructed,
            "identity_passes": True,
        },
        "features": {"training": feature_diag(rec, TRAIN), "development_oos": feature_diag(rec, OOS), "full_scored": feature_diag(rec, FULL)},
        "state_contributions": {"training": state_contrib(pos["candidate"], a["candidate"], TRAIN), "development_oos": state_contrib(pos["candidate"], a["candidate"], OOS), "full_scored": state_contrib(pos["candidate"], a["candidate"], FULL)},
        "oos_transitions": trans,
        "forward_diagnostics": {"training": forward_diag(rec, a["candidate"]["market"], TRAIN), "development_oos": forward_diag(rec, a["candidate"]["market"], OOS)},
        "improved_arithmetic_net_folds_vs_b1": int(sum(float(cn[k*FOLD:(k+1)*FOLD].sum() - bn[k*FOLD:(k+1)*FOLD].sum()) > 0 for k in range(12))),
    }


def checks(r: dict[str, Any]) -> dict[str, bool]:
    c = r["metrics"]["development_oos"]["candidate"]; b = r["metrics"]["development_oos"]["b1"]
    f = r["metrics"]["full_scored"]["candidate"]; br = r["breadth"]; u = r["uncertainty"]
    rs = r["residual_sharpe"]["vs_b1"]; con = br["positive_fold_concentration"]
    return {
        "positive_oos_net": c["net_return"] > 0,
        "positive_oos_sharpe": c["sharpe"] is not None and c["sharpe"] > 0,
        "net_at_least_b1": c["net_return"] >= b["net_return"],
        "sharpe_at_least_b1": c["sharpe"] is not None and b["sharpe"] is not None and c["sharpe"] >= b["sharpe"],
        "drawdown_no_worse_b1": c["max_drawdown"] >= b["max_drawdown"],
        "turnover_no_greater_b1": c["turnover"] <= b["turnover"],
        "edge_per_turnover_at_least_b1": c["edge_per_turnover_bps"] is not None and b["edge_per_turnover_bps"] is not None and c["edge_per_turnover_bps"] >= b["edge_per_turnover_bps"],
        "profitable_folds_at_least_7": br["profitable_folds"] >= 7,
        "profitable_years_at_least_3": br["profitable_years"] >= 3,
        "positive_residual_sharpe_b1": rs is not None and rs > 0,
        "mean_delta_lower_95_positive": u["annualized_mean_delta"]["lower_95"] > 0,
        "sharpe_delta_lower_95_positive": u["sharpe_delta"]["lower_95"] > 0,
        "positive_fold_concentration_at_most_half": con is not None and con <= 0.5,
        "positive_full_scored_net": f["net_return"] > 0,
    }


def run(d: pd.DataFrame, market: str) -> dict[str, Any]:
    f = features(d); pos, rec = positions(d, f); a = {k: pack(d, p) for k, p in pos.items()}
    metrics = {name: {k: metric(a[k], pos[k], span) for k in pos} for name, span in (("training", TRAIN), ("development_oos", OOS), ("full_scored", FULL))}
    br = breadth(a["candidate"]["net"], d.index)
    u = bootstrap(a["candidate"]["net"], a["b1"]["net"])
    result = {
        "market": market, "source": {"artifact_id": ART[market], "csv_sha256": HASH[market], "observations": len(d), "parsed_prefix": N},
        "metrics": metrics, "breadth": br, "uncertainty": u,
        "residual_sharpe": {"vs_b1": sharpe(a["candidate"]["net"][OOS[0]:OOS[1]] - a["b1"]["net"][OOS[0]:OOS[1]]), "vs_b0": sharpe(a["candidate"]["net"][OOS[0]:OOS[1]] - a["b0"]["net"][OOS[0]:OOS[1]])},
        "diagnostics": selector_diag(rec, pos, a),
    }
    result["acceptance"] = checks(result)
    result["passes_all"] = bool(all(result["acceptance"].values()))
    return native(result)


def protocol() -> dict[str, Any]:
    return {
        "issue": ISSUE, "family_id": FAMILY, "research_parent": "5a0fcc97d1a882f8223656c51f5bb8055f534e38",
        "candidate_count": 1, "parameter_grid_count": 0, "bar": "1H", "canonical_fee_one_way": FEE,
        "sources": {m: {"artifact_id": ART[m], "csv_sha256": HASH[m], "provider": "OKX public confirmed SPOT"} for m in HASH},
        "sample": {"warmup": list((0,2880)), "training": list(TRAIN), "development_oos": list(OOS), "full_scored": list(FULL), "parsed_prefix_bars": N, "folds": 12, "fold_hours": FOLD, "later_suffix_unread": True},
        "feature": {"energy": "sum squared signed hourly log returns", "risk_trigger": "D720>U720 and S168_recent>S168_prior", "risk_clear": "D720<=U720 and S168_recent<=S168_prior"},
        "policy": {"decision_cadence": "daily completed 00:00 UTC", "execution": "next hourly open", "exposure_states": [0,0.5,1], "base_exit": "immediate zero when 2160H trend non-positive", "hysteresis": "1->0.5 on trigger; 0.5->1 only on clear", "fees": "5 bps per absolute exposure change"},
        "benchmarks": {"B0": "hourly 2160H endpoint trend long/cash", "B1": "daily 00:00 UTC 2160H endpoint trend long/cash"},
        "uncertainty": {"resamples": 5000, "block_hours": 168, "paired_non_circular": True, "seed": SEED},
    }


def report(out: dict[str, Any]) -> str:
    def pct(x: float | None) -> str: return "—" if x is None else f"{100*x:+.2f}%"
    def num(x: float | None, n=3) -> str: return "—" if x is None else f"{x:.{n}f}"
    lines = [
        "# Downside-semivariance persistence risk-state sizing — terminal report", "",
        "## Objective and frozen architecture", "",
        "Test one own-history-only partial-risk architecture. Under a positive daily 2,160H trend, exposure is normally 1.0 and falls to 0.5 only when trailing 720H downside squared-return energy exceeds upside energy while the latest 168H downside-energy share is still increasing versus the prior 168H. Return to 1.0 requires both inequalities to clear. Candidate count was **1**, with **zero parameter-grid variants**, daily next-open execution and exactly **5 bps one way** on every absolute exposure change.", "",
        f"```text\nfamily_id       {FAMILY}\nissue           #{ISSUE}\nresearch_parent 5a0fcc97d1a882f8223656c51f5bb8055f534e38\nbar             1H\nfee             5 bps one way\n```", "",
        "## Immutable data and sample", "",
        "| Item | Frozen value |", "|---|---|", "| Provider | Public confirmed OKX SPOT |", "| Targets | BTC-USDT and ETH-USDT independently |", "| Exogenous series | None |", "| Source observations | 43,941 per market |", "| Parsed immutable prefix | 43,441 bars |", "| Training | `[2,880, 17,520)` |", "| Development OOS | `[17,520, 43,440)` |", "| Full scored | `[2,880, 43,440)` |", "| OOS folds | 12 × 2,160H |", "| Uncertainty | 5,000 paired non-circular 168H blocks, seed 20260730 |", "| Later suffix | Unread and unscored |", "",
        "## Performance", "",
    ]
    for sample in ("training", "development_oos", "full_scored"):
        lines += [f"### {sample.replace('_',' ').title()}", "", "| Market | Policy | Net | Sharpe | Max DD | Turnover | Fees | Edge/turn (bps) | Mean exposure |", "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
        for market in ("BTC-USDT", "ETH-USDT"):
            for pol in ("candidate", "b0", "b1"):
                m = out["markets"][market]["metrics"][sample][pol]
                lines.append(f"| {market} | {pol.upper()} | {pct(m['net_return'])} | {num(m['sharpe'])} | {pct(m['max_drawdown'])} | {m['turnover']:.2f} | {pct(m['fees'])} | {num(m['edge_per_turnover_bps'],2)} | {100*m['mean_exposure']:.2f}% |")
        lines.append("")
    lines += ["## Breadth and uncertainty", "", "| Market | Profitable folds | Profitable years | Concentration | Residual Sharpe vs B1 | Mean Δ 95% interval | Sharpe Δ 95% interval |", "|---|---:|---:|---:|---:|---:|---:|"]
    for market in ("BTC-USDT", "ETH-USDT"):
        r = out["markets"][market]; b = r["breadth"]; u = r["uncertainty"]
        lines.append(f"| {market} | {b['profitable_folds']}/12 | {b['profitable_years']}/4 | {pct(b['positive_fold_concentration'])} | {num(r['residual_sharpe']['vs_b1'])} | [{pct(u['annualized_mean_delta']['lower_95'])}, {pct(u['annualized_mean_delta']['upper_95'])}] | [{num(u['sharpe_delta']['lower_95'])}, {num(u['sharpe_delta']['upper_95'])}] |")
    lines += ["", "## State and failure diagnostics", ""]
    for market in ("BTC-USDT", "ETH-USDT"):
        r = out["markets"][market]; d = r["diagnostics"]; feat = d["features"]; dec = d["oos_exposure_decomposition"]
        lines += [f"### {market}", "", f"- Training trigger rate: **{100*feat['training']['risk_trigger_rate']:.2f}%**; development OOS: **{100*feat['development_oos']['risk_trigger_rate']:.2f}%**.", f"- OOS half-exposure hours: **{r['metrics']['development_oos']['candidate']['half_exposure_hours']:,}**; full-exposure hours: **{r['metrics']['development_oos']['candidate']['full_exposure_hours']:,}**.", f"- Candidate-less exposure versus B1: **{dec['candidate_less_exposure_hours']:,.1f} exposure-hours**; market contribution delta **{pct(dec['exposure_delta_market_arithmetic_return'])}**; incremental fees **{pct(dec['incremental_fees_candidate_minus_b1'])}**.", f"- OOS folds with improved arithmetic net versus B1: **{d['improved_arithmetic_net_folds_vs_b1']}/12**.", ""]
    verdict = out["verdict"]
    lines += ["## Verdict", "", f"```text\n{verdict}\n```", "", "No window, exposure fraction, inequality, hysteresis, cadence, fee, market-specific or uncertainty rescue is authorised on this consumed interval.", "", "## Remaining blocker and next experiment", "", out["remaining_blocker"], "", f"**Next experiment:** {out['next_experiment']}", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--btc", type=Path, required=True); ap.add_argument("--eth", type=Path, required=True); ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    markets = {"BTC-USDT": run(load(args.btc, "BTC-USDT"), "BTC-USDT"), "ETH-USDT": run(load(args.eth, "ETH-USDT"), "ETH-USDT")}
    accepted = all(v["passes_all"] for v in markets.values())
    out = {
        "issue": ISSUE, "family_id": FAMILY, "candidate_count": 1, "parameter_grid_count": 0,
        "markets": markets, "accepted": accepted,
        "verdict": "accept_exact_downside_semivariance_persistence_risk_state_family" if accepted else "reject_exact_downside_semivariance_persistence_risk_state_family",
        "remaining_blocker": "The downside-asymmetry state is not economically transportable across the two development markets: it removed profitable BTC carry, while ETH point estimates improved but remained too narrow and uncertain to qualify.",
        "next_experiment": "Preregister one own-history-only bipower-jump-concentration trend-carry architecture: retain the 2,160H base trend, estimate fixed 720H realized variance and bipower variation, and use a partial risk state only when the latest 168H jump-variation share is both above its preceding 168H value and accompanied by a negative 168H return; one candidate, no fitted threshold, no market-specific rule and no forced hold.",
        "repaired_discrepancy": "The first diagnostic version filtered turnover transitions by decision index rather than execution index. It was repaired to attribute every transition to the next-open bar that actually incurs turnover and fees. The complete experiment was rerun; no signal, exposure, metric, gate, bootstrap result or verdict changed.",
    }
    (args.output_dir / "protocol.json").write_text(json.dumps(protocol(), indent=2, sort_keys=True) + "\n")
    (args.output_dir / "result.json").write_text(json.dumps(native(out), indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(report(out))
    print(json.dumps({"accepted": accepted, "verdict": out["verdict"], "summary": {m: {"training": r["metrics"]["training"]["candidate"], "oos": r["metrics"]["development_oos"]["candidate"], "b1_oos": r["metrics"]["development_oos"]["b1"], "full": r["metrics"]["full_scored"]["candidate"], "breadth": r["breadth"], "uncertainty": r["uncertainty"], "residual": r["residual_sharpe"], "acceptance": r["acceptance"], "diag": r["diagnostics"]} for m,r in markets.items()}}, indent=2))

if __name__ == "__main__": main()
