from __future__ import annotations

import argparse, hashlib, json, math, tempfile, zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ARTIFACT_SHA = "85e51d072bd4fc7388421b411b58fd5d36ec10380b23ad7a179c0a98f153643a"
MARKETS = ("BTC-USDT", "ETH-USDT")
HASHES = {
    "BTC-USDT": ("c894d275ebf77a693c91f998a2ed6d25feb332b096106dafe5dde1bf648fceae", "d3afdc61486d8a02f2f87ee1495998b99be4531186ff4608cefcaadf488cc2d4"),
    "ETH-USDT": ("149767fd07c421c78903af0734d7c70408fcd57be7e4901ac0c3fcfa5d0d8da0", "c24d408d40199db6fedf3ec334ca8dc33ce1cecc84054aaebe5dfaaf915fa2db"),
}
FEE, HOUR_MS, BLOCK, N_BOOT, SEED = 0.0005, 3_600_000, 6, 5_000, 20260729


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def cjson(x: object) -> bytes:
    return (json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def comp(x: np.ndarray) -> float:
    return float(np.prod(1 + x) - 1)


def shrp(x: np.ndarray) -> float | None:
    s = float(np.std(x))
    return None if s <= 0 else float(np.mean(x) / s * math.sqrt(8760))


def dd(x: np.ndarray) -> float:
    n = np.cumprod(1 + x)
    return float(np.min(n / np.maximum.accumulate(n) - 1))


def features(a: pd.DataFrame, market: str, full: bool = True) -> pd.DataFrame:
    if set(a.instrument_name.astype(str)) != {market}:
        raise ValueError("mixed instrument")
    a = a.copy()
    a.trade_id = a.trade_id.astype("int64")
    a.created_time = a.created_time.astype("int64")
    a = a.sort_values(["created_time", "trade_id"], kind="mergesort")
    if a.trade_id.duplicated().any() or (a.created_time.diff().dropna() < 0).any():
        raise ValueError("bad chronology")
    a["hour"] = a.created_time // HOUR_MS * HOUR_MS
    a["q"] = a.price.astype(float) * a["size"].astype(float)
    a["sq"] = np.where(a.side.eq("buy"), a.q, -a.q)
    out = []
    for hour, g in a.groupby("hour", sort=True):
        gaps = np.diff(g.created_time.to_numpy(np.int64)) / 1000
        mu, sd = float(gaps.mean()), float(gaps.std())
        if len(gaps) == 0 or mu <= 0:
            raise ValueError("invalid inter-arrivals")
        b = (sd - mu) / (sd + mu)
        flow = float(g.sq.sum() / g.q.sum())
        out.append((pd.Timestamp(int(hour), unit="ms", tz="UTC"), len(g), flow, b, max(0.0, flow) * max(0.0, b), max(0.0, flow)))
    f = pd.DataFrame(out, columns=["timestamp", "count", "flow", "burst", "candidate", "raw"]).set_index("timestamp")
    if full:
        expected = pd.date_range(f.index[0], periods=24, freq="h", tz="UTC")
        if len(f) != 24 or not f.index.equals(expected):
            raise ValueError("not 24 consecutive hours")
    return f


def path(position: pd.Series, fwd: pd.Series) -> pd.DataFrame:
    p = position.astype(float).clip(0, 1)
    turn = (p - p.shift(1).fillna(0)).abs()
    fee, gross = turn * FEE, p * fwd
    net = gross - fee
    turn.iloc[-1] += p.iloc[-1]
    fee.iloc[-1] += p.iloc[-1] * FEE
    net.iloc[-1] -= p.iloc[-1] * FEE
    return pd.DataFrame({"position": p, "turnover": turn, "fee": fee, "gross": gross, "net": net})


def metrics(x: pd.DataFrame) -> dict[str, object]:
    n, g = x.net.to_numpy(float), x.gross.to_numpy(float)
    t = float(x.turnover.sum())
    blocks = [comp(n[i:i+6]) for i in range(0, 24, 6)]
    pos = [v for v in blocks if v > 0]
    return {
        "gross_return": comp(g), "net_return": comp(n), "sharpe": shrp(n), "max_drawdown": dd(n),
        "turnover": t, "fee_burden_arithmetic": float(x.fee.sum()),
        "edge_per_turnover_bps": None if t <= 0 else float(n.sum() / t * 1e4),
        "mean_position": float(x.position.mean()), "no_trade_frequency": float((x.position == 0).mean()),
        "position_adjustments": int((x.turnover > 0).sum()), "profitable_6h_blocks": sum(v > 0 for v in blocks),
        "positive_block_concentration": None if not pos else float(max(pos) / sum(pos)),
    }


def market(root: Path, name: str):
    ap, cp = root/name/"archive.csv", root/name/"candles/candles.csv"
    if (sha(ap), sha(cp)) != HASHES[name]:
        raise ValueError("input hash mismatch")
    a, c = pd.read_csv(ap), pd.read_csv(cp)
    f = features(a, name)
    c.timestamp = pd.to_datetime(c.timestamp, utc=True)
    c = c.set_index("timestamp").sort_index()
    if not c.confirm.eq(1).all():
        raise ValueError("unconfirmed candle")
    close = c.close.astype(float)
    cur, nxt = close.reindex(f.index), close.shift(-1).reindex(f.index)
    if cur.isna().any() or nxt.isna().any():
        raise ValueError("missing payoff candle")
    ret = pd.Series(nxt.to_numpy()/cur.to_numpy()-1, index=f.index)
    old = close.reindex(f.index - pd.Timedelta(hours=2160))
    if old.isna().any():
        raise ValueError("missing trend prehistory")
    trend = pd.Series((cur.to_numpy()/old.to_numpy()-1 > 0).astype(float), index=f.index)
    paths = {"burst_flow": path(f.candidate, ret), "raw_flow": path(f.raw, ret), "trend": path(trend, ret)}
    cutoff = f.index[12]
    prefix = features(a[pd.to_datetime(a.created_time, unit="ms", utc=True) < cutoff], name, False)
    if not np.allclose(prefix[["flow","burst","candidate"]], f.loc[f.index < cutoff, ["flow","burst","candidate"]], atol=1e-15, rtol=0):
        raise AssertionError("future suffix changed prefix")
    return {
        "trade_rows": len(a), "feature_hours": len(f), "missing_hours": 0,
        "sample_start": f.index[0].isoformat(), "sample_end_exclusive": (f.index[-1]+pd.Timedelta(hours=1)).isoformat(),
        "burstiness": {"min": float(f.burst.min()), "median": float(f.burst.median()), "max": float(f.burst.max())},
        "policies": {k: metrics(v) for k,v in paths.items()},
        "causal_tests": {"chronology":"pass","complete_grid":"pass","future_suffix":"pass","next_hour":"pass","fees":"pass"},
    }, paths


def inference(paths):
    res = {}
    for m in MARKETS:
        b, r, t = (paths[m][k].net.to_numpy(float) for k in ("burst_flow","raw_flow","trend"))
        res[m] = {"raw": b-r, "trend": b-t}
    names = ("burst_minus_raw_mean_hour", "burst_minus_trend_mean_hour")
    observed = {names[0]: min(float(res[m]["raw"].mean()) for m in MARKETS), names[1]: min(float(res[m]["trend"].mean()) for m in MARKETS)}
    rng, samples = np.random.default_rng(SEED), {n: [] for n in names}
    for _ in range(N_BOOT):
        starts = rng.integers(0, 22-BLOCK+1, size=math.ceil(22/BLOCK))
        interior = np.concatenate([np.arange(s,s+BLOCK) for s in starts])[:22] + 1
        idx = np.r_[0, interior, 23]
        samples[names[0]].append(min(float(res[m]["raw"][idx].mean()) for m in MARKETS))
        samples[names[1]].append(min(float(res[m]["trend"][idx].mean()) for m in MARKETS))
    ends, rawp = {}, {}
    for n in names:
        x = np.asarray(samples[n]); p = float((1+(x<=0).sum())/(len(x)+1)); rawp[n]=p
        ends[n] = {"observed": observed[n], "one_sided_95pct_lower_bound": float(np.quantile(x,.05)), "raw_one_sided_p": p}
    running = 0.0
    for rank,n in enumerate(sorted(rawp,key=rawp.get)):
        running = max(running, min(1.0, rawp[n]*(len(names)-rank))); ends[n]["holm_adjusted_p"] = running
    return {"resamples":N_BOOT,"block_hours":BLOCK,"paired_common_calendar":True,"boundary_rows_retained_exactly_once":True,"holm_family_size":2,"endpoints":ends}


def main():
    p = argparse.ArgumentParser(); p.add_argument("artifact",type=Path); p.add_argument("output",type=Path); a=p.parse_args()
    if sha(a.artifact) != ARTIFACT_SHA: raise ValueError("artifact hash mismatch")
    with tempfile.TemporaryDirectory() as d:
        with zipfile.ZipFile(a.artifact) as z: z.extractall(d)
        results, paths = {}, {}
        for m in MARKETS: results[m], paths[m] = market(Path(d), m)
        inf = inference(paths)
    fail=[]
    for m in MARKETS:
        c,r,t=(results[m]["policies"][k] for k in ("burst_flow","raw_flow","trend"))
        if c["edge_per_turnover_bps"] is None or c["edge_per_turnover_bps"] <= 0: fail.append(f"{m}: non-positive edge")
        if c["net_return"] <= t["net_return"]: fail.append(f"{m}: below trend")
        if c["profitable_6h_blocks"] < 2: fail.append(f"{m}: fold breadth")
        if c["positive_block_concentration"] is None or c["positive_block_concentration"] > .5: fail.append(f"{m}: concentration")
    for n,e in inf["endpoints"].items():
        if e["one_sided_95pct_lower_bound"] <= 0 or e["holm_adjusted_p"] >= .05: fail.append(f"inference:{n}")
    out={"schema_version":"trade-arrival-burstiness-bounded-v1","candidate_count":1,"bar":"1H","canonical_fee_bps_one_way":5.0,"artifact_sha256":ARTIFACT_SHA,"markets":results,"statistical_inference":inf,"qualification_failures":fail,"verdict":"trade_arrival_burstiness_positive_flow_rejected_on_bounded_diagnostic" if fail else "trade_arrival_burstiness_positive_flow_supported_on_bounded_diagnostic"}
    a.output.write_bytes(cjson(out)); print(json.dumps({"verdict":out["verdict"],"failures":fail},indent=2))

if __name__ == "__main__": main()
