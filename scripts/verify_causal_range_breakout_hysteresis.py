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
FOLD, PREFIX = 2160, 43441
HASHES = {
    "BTC-USDT": "92bd223ce3898604700dd0d834b93b146ea2247cb72f8a57b112ed28e7fbbbe9",
    "ETH-USDT": "2845617652dd4017caa0447838e980da49c88d0328545a1fba5bf18554dc5726",
}


def load(path: Path, name: str) -> pd.DataFrame:
    if hashlib.sha256(path.read_bytes()).hexdigest() != HASHES[name]:
        raise ValueError(f"{name} source hash mismatch")
    df = pd.read_csv(path, nrows=PREFIX)
    ts = pd.DatetimeIndex(pd.to_datetime(df.timestamp, utc=True))
    expected = pd.date_range(ts[0], periods=PREFIX, freq="1h", tz="UTC")
    px = df[["open", "high", "low", "close"]].to_numpy(float)
    valid = (
        len(df) == PREFIX
        and ts.equals(expected)
        and ts.is_unique
        and (df.confirm == 1).all()
        and np.isfinite(px).all()
        and (px > 0).all()
        and (df.high >= df[["open", "close"]].max(axis=1)).all()
        and (df.low <= df[["open", "close"]].min(axis=1)).all()
    )
    if not valid:
        raise ValueError(f"{name} invalid confirmed contiguous 1H prefix")
    df.index = ts
    return df


def positions(df: pd.DataFrame) -> dict[str, np.ndarray]:
    n, close = len(df), df.close.to_numpy(float)
    high, low = df.high.to_numpy(float), df.low.to_numpy(float)
    out = {k: np.zeros(n - 1) for k in ("candidate", "b0", "b1")}
    state = b1 = 0.0
    for t in range(2160, n - 1):
        endpoint = float(close[t] > close[t - 2160])
        if df.index[t].hour == 0:
            entry = float(np.max(high[t - 2160 : t]))
            exit_ = float(np.min(low[t - 720 : t]))
            if state == 0 and close[t] > entry:
                state = 1.0
            elif state == 1 and close[t] < exit_:
                state = 0.0
            b1 = endpoint
        j = t + 1
        if j < n - 1:
            out["candidate"][j] = state
            out["b0"][j] = endpoint
            out["b1"][j] = b1
    changes = np.flatnonzero(np.r_[out["candidate"][0] != 0, np.diff(out["candidate"]) != 0])
    if any(df.index[int(j) - 1].hour != 0 for j in changes if j > 0):
        raise ValueError("candidate changed outside daily next-open boundary")
    return out


def returns(df: pd.DataFrame, pos: np.ndarray) -> np.ndarray:
    market = df.open.to_numpy(float)[1:] / df.open.to_numpy(float)[:-1] - 1
    turnover = np.r_[abs(pos[0]), np.abs(np.diff(pos))]
    return pos * market - FEE * turnover


def sharpe(x: np.ndarray) -> float | None:
    sd = float(np.std(x, ddof=1))
    return None if sd <= 0 else float(math.sqrt(ANN) * np.mean(x) / sd)


def metrics(net: np.ndarray, pos: np.ndarray, span: tuple[int, int]) -> dict[str, float | int | None]:
    a, z = span
    x, p = net[a:z], pos[a:z]
    turn = np.r_[abs(pos[0]), np.abs(np.diff(pos))][a:z]
    wealth = np.cumprod(1 + x)
    path = np.r_[1.0, wealth]
    turnover = float(turn.sum())
    return {
        "net_return": float(wealth[-1] - 1),
        "sharpe": sharpe(x),
        "max_drawdown": float(np.min(path / np.maximum.accumulate(path) - 1)),
        "turnover": turnover,
        "fees": float(FEE * turnover),
        "edge_per_turnover_bps": float(x.sum() / turnover * 10000) if turnover else None,
        "exposure": float(p.mean()),
    }


def verify_close(actual: float | None, expected: float | None, label: str) -> None:
    if actual is None or expected is None:
        if actual is not expected:
            raise ValueError(f"{label} null mismatch")
    elif not math.isclose(actual, expected, rel_tol=0, abs_tol=1e-12):
        raise ValueError(f"{label} mismatch: {actual} != {expected}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--btc-csv", type=Path, required=True)
    parser.add_argument("--eth-csv", type=Path, required=True)
    parser.add_argument("--expected-result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    expected = json.loads(args.expected_result.read_text())
    frames = {
        "BTC-USDT": load(args.btc_csv, "BTC-USDT"),
        "ETH-USDT": load(args.eth_csv, "ETH-USDT"),
    }
    spans = {"training": TRAIN, "development_oos": OOS, "full_scored": FULL}
    verified: dict[str, object] = {}
    for name, df in frames.items():
        pos = positions(df)
        nets = {policy: returns(df, values) for policy, values in pos.items()}
        observed = {
            span_name: {
                policy: metrics(nets[policy], pos[policy], span)
                for policy in ("candidate", "b0", "b1")
            }
            for span_name, span in spans.items()
        }
        persisted = expected["markets"][name]["metrics"]
        for span_name in spans:
            for policy in ("candidate", "b0", "b1"):
                for key, value in observed[span_name][policy].items():
                    verify_close(value, persisted[span_name][policy][key], f"{name}.{span_name}.{policy}.{key}")
        folds = [
            float(np.prod(1 + nets["candidate"][OOS[0] + k * FOLD : OOS[0] + (k + 1) * FOLD]) - 1)
            for k in range(12)
        ]
        persisted_folds = expected["markets"][name]["breadth"]["fold_returns"]
        for i, value in enumerate(folds):
            verify_close(value, persisted_folds[i], f"{name}.fold[{i}]")
        verified[name] = {"metrics": observed, "fold_returns": folds}
    output = {
        "family_id": expected["family_id"],
        "result_sha256": hashlib.sha256(args.expected_result.read_bytes()).hexdigest(),
        "verdict": expected["verdict"],
        "verified": verified,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
