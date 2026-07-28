"""Reproduce the bounded sell-flow absorption strategy diagnostic.

Inputs are extracted immutable artifacts:
- trade-flow checkpoint artifact 8691619707
- canonical BTC/ETH 1H artifacts 8685574446 / 8685572234
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

FEE = 0.0005
HOURS_PER_YEAR = 8760.0
EXPECTED_TRADE_ZIP_SHA256 = (
    "275dd35af6ab74c42b8aac2e272af274dbe9256cca3609345ee8dfa76d524932"
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sharpe(values: np.ndarray) -> float | None:
    sd = float(np.std(values, ddof=1))
    return None if sd == 0 else float(np.mean(values) / sd * math.sqrt(HOURS_PER_YEAR))


def max_drawdown(values: np.ndarray) -> float:
    nav = np.r_[1.0, np.cumprod(1.0 + values)]
    return float(np.min(nav / np.maximum.accumulate(nav) - 1.0))


def hourly_trade_features(path: Path, market: str) -> pd.DataFrame:
    trades = pd.read_csv(path)
    if set(trades["instrument_name"].unique()) != {market}:
        raise ValueError(f"{market}: mixed instrument archive")
    if trades["trade_id"].duplicated().any():
        raise ValueError(f"{market}: duplicate trade identity")
    trades["created_time"] = pd.to_numeric(trades["created_time"], errors="raise").astype("int64")
    trades["price"] = pd.to_numeric(trades["price"], errors="raise")
    trades["size"] = pd.to_numeric(trades["size"], errors="raise")
    trades = trades.sort_values(["created_time", "trade_id"], kind="mergesort")
    id_order = trades.sort_values("trade_id")
    if (id_order["created_time"].diff().dropna() < 0).any():
        raise ValueError(f"{market}: trade-ID/time inversion")
    trades["hour"] = pd.to_datetime(
        (trades["created_time"] // 3_600_000) * 3_600_000, unit="ms", utc=True
    )
    observed = pd.DatetimeIndex(sorted(trades["hour"].unique()))
    expected = pd.date_range(observed[0], periods=24, freq="h", tz="UTC")
    if len(observed) != 24 or not observed.equals(expected):
        raise ValueError(f"{market}: incomplete 24H archive grid")

    rows = []
    for hour, group in trades.groupby("hour", sort=True):
        notional = group["price"] * group["size"]
        signed = np.where(group["side"].eq("buy"), notional, -notional)
        flow = float(np.sum(signed) / np.sum(notional))
        impact = float(math.log(group.iloc[-1]["price"] / group.iloc[0]["price"]))
        rows.append(
            {
                "feature_hour": hour,
                "flow": flow,
                "impact_return": impact,
                "target": float(flow < 0.0 and impact >= 0.0),
            }
        )
    return pd.DataFrame(rows)


def candles(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    if frame["timestamp"].duplicated().any() or not frame["timestamp"].is_monotonic_increasing:
        raise ValueError("invalid candle chronology")
    if not (frame["timestamp"].diff().dropna() == pd.Timedelta(hours=1)).all():
        raise ValueError("gapped candle grid")
    if not (frame["confirm"] == 1).all():
        raise ValueError("unconfirmed candle")
    frame["next_open_return"] = frame["open"].shift(-1) / frame["open"] - 1.0
    frame["simple_trend_target"] = (
        frame["close"] / frame["close"].shift(2160) - 1.0 > 0.0
    ).astype(float)
    return frame.set_index("timestamp")


def metrics(net: np.ndarray, gross: np.ndarray, turnover: np.ndarray) -> dict[str, float | int | None]:
    total_turnover = float(turnover.sum())
    return {
        "observations": len(net),
        "net_return": float(np.prod(1.0 + net) - 1.0),
        "gross_return": float(np.prod(1.0 + gross) - 1.0),
        "sharpe": sharpe(net),
        "max_drawdown": max_drawdown(net),
        "turnover": total_turnover,
        "edge_per_turnover_bps": (
            None if total_turnover == 0 else float(net.sum() / total_turnover * 10_000)
        ),
        "modeled_fee_burden": total_turnover * FEE,
    }


def run_market(root: Path, market: str) -> dict[str, object]:
    feature = hourly_trade_features(
        root / "tradeflow_artifact" / "trade-flow-schema-checkpoint" / market / "archive.csv",
        market,
    )
    canonical_name = "btc_canonical" if market == "BTC-USDT" else "eth_canonical"
    price = candles(root / canonical_name / "snapshot" / f"okx-{market}-1H.csv")

    asset_returns = []
    trend_targets = []
    for row in feature.itertuples(index=False):
        decision_open = row.feature_hour + pd.Timedelta(hours=1)
        asset_returns.append(float(price.loc[decision_open, "next_open_return"]))
        # Causal repair: benchmark uses completed feature-hour close, not execution-hour close.
        trend_targets.append(float(price.loc[row.feature_hour, "simple_trend_target"]))

    positions = feature["target"].to_numpy(float)
    returns = np.asarray(asset_returns)
    turnover = np.abs(positions - np.r_[0.0, positions[:-1]])
    gross = positions * returns
    net = gross - FEE * turnover
    # Symmetric bounded-period exit.
    net[-1] -= FEE * positions[-1]
    turnover[-1] += positions[-1]

    trend = np.asarray(trend_targets)
    trend_turnover = np.abs(trend - np.r_[0.0, trend[:-1]])
    trend_gross = trend * returns
    trend_net = trend_gross - FEE * trend_turnover
    trend_net[-1] -= FEE * trend[-1]
    trend_turnover[-1] += trend[-1]

    return {
        "market": market,
        "feature_hours": len(feature),
        "signal_hours": int(positions.sum()),
        "candidate": metrics(net, gross, turnover),
        "simple_trend": metrics(trend_net, trend_gross, trend_turnover),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    trade_zip = args.root / "trade-flow-checkpoint.zip"
    if sha256(trade_zip) != EXPECTED_TRADE_ZIP_SHA256:
        raise ValueError("trade artifact ZIP hash mismatch")
    result = {
        "hypothesis": "long next hour iff completed-hour flow < 0 and impact >= 0",
        "fee_bps_one_way": 5.0,
        "markets": [run_market(args.root, market) for market in ("BTC-USDT", "ETH-USDT")],
    }
    encoded = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    args.output.write_bytes(encoded)
    print(json.dumps(result, indent=2))
    print("sha256", hashlib.sha256(encoded).hexdigest())


if __name__ == "__main__":
    main()
