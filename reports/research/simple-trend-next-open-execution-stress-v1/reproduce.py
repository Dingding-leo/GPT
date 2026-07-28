from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

H, L, F, B, N, SEED = 8760.0, 2160, 0.0005, 168, 5000, 20260728
D0, D1 = pd.Timestamp("2023-07-24T00:00:00Z"), pd.Timestamp("2026-07-07T23:00:00Z")
X0, X1 = pd.Timestamp("2026-07-08T00:00:00Z"), pd.Timestamp("2026-07-28T08:00:00Z")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def verify(root: Path) -> None:
    for line in (root / "artifact-manifest.sha256").read_text().splitlines():
        digest, rel = line.split("  ", 1)
        assert sha(root / rel) == digest, rel


def sr(r: np.ndarray) -> float:
    s = np.std(r, ddof=1)
    return float(np.mean(r) / s * math.sqrt(H)) if s > 0 else 0.0


def dd(r: np.ndarray) -> float:
    nav = np.cumprod(1 + r)
    return float(np.min(nav / np.maximum.accumulate(nav) - 1))


def metrics(r: np.ndarray, t: np.ndarray, p: np.ndarray) -> dict:
    years = len(r) / H
    ann = float(np.mean(r) * H)
    turn = float(np.sum(t) / years)
    return {
        "total_net_return": float(np.prod(1 + r) - 1),
        "annualized_arithmetic_mean": ann,
        "annualized_sharpe": sr(r),
        "max_drawdown": dd(r),
        "annualized_turnover": turn,
        "modeled_fee_sum": float(F * np.sum(t)),
        "edge_per_turnover_bps": float(ann / turn * 1e4) if turn else None,
        "transition_count": int(np.count_nonzero(t > 1e-15)),
        "time_in_market": float(np.mean(p)),
    }


def path(
    df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    lag: int,
    open_return: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ids = np.flatnonzero(((df.timestamp >= start) & (df.timestamp <= end)).to_numpy())
    p = df.target.shift(lag).to_numpy(float)[ids]
    raw = df.open.shift(-1) / df.open - 1 if open_return else df.close.pct_change()
    mr = raw.to_numpy(float)[ids]
    prev = np.r_[0.0, p[:-1]]
    t = np.abs(p - prev)
    r = p * mr - F * t
    assert np.isfinite(r).all()
    return r, t, p


def indices(rng: np.random.Generator) -> np.ndarray:
    out = []
    for fold in range(12):
        base = fold * 2160
        out.append(np.array([base]))
        blocks = []
        while sum(map(len, blocks)) < 2159:
            s = int(rng.integers(1, 2160 - B + 1))
            blocks.append(base + np.arange(s, s + B))
        out.append(np.concatenate(blocks)[:2159])
    return np.concatenate(out)


def holm(ps: dict[str, float]) -> dict[str, float]:
    items = sorted(ps.items(), key=lambda x: x[1])
    m = len(items)
    run = 0.0
    out = {}
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--btc", type=Path, required=True)
    ap.add_argument("--eth", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    roots = {"BTC-USDT": a.btc, "ETH-USDT": a.eth}
    series = {}
    result = {
        "markets": {},
        "bootstrap": {},
        "fee_one_way_bps": 5.0,
        "lookback_hours": 2160,
    }
    for market, root in roots.items():
        verify(root)
        snap = next((root / "snapshot").glob("*.csv"))
        df = pd.read_csv(snap, parse_dates=["timestamp"])
        assert (
            len(df) == 43930
            and df.timestamp.is_unique
            and df.timestamp.is_monotonic_increasing
        )
        assert (df.timestamp.diff().dropna() == pd.Timedelta(hours=1)).all()
        assert (df.confirm == 1).all()
        df["target"] = (df.close / df.close.shift(L) - 1 > 0).astype(float)
        wf = pd.read_csv(root / "walk_forward_returns.csv")
        paths = {
            "C0": path(df, D0, D1, 1, False),
            "C1": path(df, D0, D1, 1, True),
            "C2": path(df, D0, D1, 2, True),
        }
        assert (
            np.max(
                np.abs(
                    paths["C0"][0]
                    - wf.benchmark_simple_trend_long_cash_return.to_numpy()
                )
            )
            < 1e-12
        )
        fresh = {
            "C0": path(df, X0, X1, 1, False),
            "C1": path(df, X0, X1, 1, True),
            "C2": path(df, X0, X1, 2, True),
        }
        result["markets"][market] = {
            "development": {k: metrics(*v) for k, v in paths.items()},
            "fresh": {k: metrics(*v) for k, v in fresh.items()},
        }
        series[market] = paths
    endpoint = {}
    observed = {}
    pairs = [("C1", "C0"), ("C2", "C1")]
    for market, paths in series.items():
        for x, y in pairs:
            observed[f"{market}_{x}-{y}_mean"] = float(
                np.mean(paths[x][0] - paths[y][0]) * H
            )
            observed[f"{market}_{x}-{y}_sharpe"] = sr(paths[x][0]) - sr(paths[y][0])
            endpoint[f"{market}_{x}-{y}_mean"] = []
            endpoint[f"{market}_{x}-{y}_sharpe"] = []
    rng = np.random.default_rng(SEED)
    for _ in range(N):
        ix = indices(rng)
        for market, paths in series.items():
            for x, y in pairs:
                endpoint[f"{market}_{x}-{y}_mean"].append(
                    float(np.mean(paths[x][0][ix] - paths[y][0][ix]) * H)
                )
                endpoint[f"{market}_{x}-{y}_sharpe"].append(
                    sr(paths[x][0][ix]) - sr(paths[y][0][ix])
                )
    raw = {}
    stats = {}
    for k, values in endpoint.items():
        v = np.asarray(values)
        o = observed[k]
        e = v - o
        p = float((1 + np.sum(e >= o)) / (N + 1))
        raw[k] = p
        stats[k] = {
            "observed": o,
            "one_sided_95_lower": float(2 * o - np.quantile(v, 0.95)),
            "raw_p": p,
        }
    adjusted = holm(raw)
    for k, p in adjusted.items():
        stats[k]["holm_p"] = p
    result["bootstrap"] = {
        "resamples": N,
        "block_hours": B,
        "seed": SEED,
        "endpoints": stats,
    }
    result["verdict"] = "retain_fixed_development_benchmark_pending_independent_replication"
    data = (
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode()
    a.out.write_bytes(data)
    print(hashlib.sha256(data).hexdigest())


if __name__ == "__main__":
    main()
