from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION = 8_760
CHANNEL = 24
REGIME = 168
VOLATILITY = 168
TARGET_VOLATILITY = 0.50
FEE = 0.0005
TEST_BARS = 2_160
START = pd.Timestamp("2023-07-01T00:00:00Z")
END = pd.Timestamp("2026-06-14T23:00:00Z")
BLOCK = 168
RESAMPLES = 2_000
TAIL = 0.05
CAPITAL = 1_000_000.0
PARTICIPATION = 0.001
LIQUIDITY_WINDOW = 720
EPSILON = 1e-12

SIGNATURE = (
    "channel-breakout-trend-1h-v1|markets=BTC-USDT,ETH-USDT|provider=OKX-spot|"
    "bar=1H|source=portable-canonical-1h-artifacts|"
    "architecture=24h-donchian-breakout-with-168h-positive-trend-regime|"
    "entry=close-above-prior-24h-high-and-168h-log-return-positive|"
    "exit=close-below-prior-24h-low-or-regime-nonpositive|"
    "size=50pct-annualized-vol-target-using-168h-realized-vol|max-position=1|"
    "fee=5bps-one-way|execution=one-complete-bar-delay|"
    "evaluation=2023-07-01T00:00Z..2026-06-14T23:00Z|fold=2160h|"
    "bootstrap=paired-noncircular-168h-blocks-2000-resamples-95pct|"
    "architecture-candidate-count=1"
)
MARKETS: dict[str, dict[str, Any]] = {
    "BTC-USDT": {
        "artifact_id": 8_586_473_477,
        "zip_sha256": "44ef21be41117768f34422bff2458ef3daf1709b6335387c8ddc9d23077ebed7",
        "manifest_sha256": "16548b4abd0f2508a4c6646c30a04117fec7686e92b9a95028d142a2f0532216",
        "snapshot": "okx-BTC-USDT-1H.csv",
        "snapshot_sha256": "bbba1e9b36e17b03ff6aed237a4de949b4a39b1d17eaf1b4979627794acb909c",
        "seed": 20_260_724_151,
    },
    "ETH-USDT": {
        "artifact_id": 8_586_463_176,
        "zip_sha256": "fa13b5333b4bdfae02fc653351ea25f203e953315dd70d318cb47a82341c528d",
        "manifest_sha256": "95d9535f9e4badd736844f3a31e8d43e067032e32b44e406affa0932dc190aa8",
        "snapshot": "okx-ETH-USDT-1H.csv",
        "snapshot_sha256": "37f33ce7a55786a10f4c8e0f7ff1c870f331792b6ba1712229008480498ea236",
        "seed": 20_260_724_152,
    },
}
BENCHMARKS = {
    "buy_and_hold": "benchmark_buy_and_hold_return",
    "volatility_targeted_long": "benchmark_volatility_targeted_long_return",
    "simple_trend_long_cash": "benchmark_simple_trend_long_cash_return",
}
NEIGHBOURS = {
    "shorter_channel": {"channel": 12},
    "longer_channel": {"channel": 36},
    "shorter_regime": {"regime": 120, "volatility": 120},
    "longer_regime": {"regime": 240, "volatility": 240},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hourly_index(values: pd.Series) -> pd.DatetimeIndex:
    raw = values.astype("string")
    if not raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False).all():
        raise ValueError("timestamps require explicit timezone")
    index = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if index.duplicated().any() or not index.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and increasing")
    if len(index) > 1 and not ((index[1:] - index[:-1]) == pd.Timedelta(hours=1)).all():
        raise ValueError("timestamps must be hourly")
    return index


def load_artifact(
    root: Path,
    market: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    spec = MARKETS[market]
    manifest = root / "artifact-manifest.sha256"
    if sha256(manifest) != spec["manifest_sha256"]:
        raise ValueError("manifest hash mismatch")
    snapshot = root / "snapshot" / str(spec["snapshot"])
    if sha256(snapshot) != spec["snapshot_sha256"]:
        raise ValueError("snapshot hash mismatch")
    effective = json.loads((root / "effective_config.json").read_text())
    report = json.loads((root / "walk_forward.json").read_text())
    if effective["data"]["bar"] != "1H":
        raise ValueError("artifact must be 1H")
    if effective["strategy"]["transaction_cost_bps"] != 5.0:
        raise ValueError("artifact fee must be 5 bps")
    if effective["robustness"]["cost_multipliers"] != [1.0]:
        raise ValueError("artifact must contain only 1x cost")
    if report["settings"]["cost_multipliers"] != [1.0]:
        raise ValueError("report must contain only 1x cost")
    candles = pd.read_csv(snapshot)
    candles.index = hourly_index(candles.pop("timestamp"))
    columns = ["open", "high", "low", "close", "volume_quote"]
    candles[columns] = candles[columns].apply(pd.to_numeric, errors="raise")
    if not np.isfinite(candles[columns].to_numpy()).all():
        raise ValueError("non-finite candle")
    returns = pd.read_csv(root / "walk_forward_returns.csv")
    returns.index = hourly_index(returns.pop("timestamp"))
    for column in BENCHMARKS.values():
        returns[column] = pd.to_numeric(returns[column], errors="raise")
    if len(returns) != 25_920 or returns.index[0] != START or returns.index[-1] != END:
        raise ValueError("OOS window mismatch")
    provenance = {
        "artifact_id": spec["artifact_id"],
        "artifact_zip_sha256": spec["zip_sha256"],
        "artifact_manifest_sha256": spec["manifest_sha256"],
        "snapshot_sha256": spec["snapshot_sha256"],
        "source_start": candles.index[0].isoformat(),
        "source_end": candles.index[-1].isoformat(),
        "source_observations": len(candles),
    }
    return candles, returns, provenance


def target_path(
    candles: pd.DataFrame,
    *,
    channel: int = CHANNEL,
    regime: int = REGIME,
    volatility: int = VOLATILITY,
) -> pd.Series:
    if min(channel, regime, volatility) < 2:
        raise ValueError("lookbacks must be at least two")
    close = candles["close"].astype(float)
    prior_high = candles["high"].shift(1).rolling(channel, min_periods=channel).max()
    prior_low = candles["low"].shift(1).rolling(channel, min_periods=channel).min()
    regime_return = np.log(close).diff(regime)
    realized = (
        np.log(close)
        .diff()
        .rolling(
            volatility,
            min_periods=volatility,
        )
        .std(ddof=0)
    )
    realized *= math.sqrt(ANNUALIZATION)
    values = np.zeros(len(candles))
    is_long = False
    for row in range(len(candles)):
        valid = all(
            math.isfinite(value)
            for value in (
                prior_high.iloc[row],
                prior_low.iloc[row],
                regime_return.iloc[row],
                realized.iloc[row],
            )
        )
        if not valid:
            is_long = False
        elif not is_long and close.iloc[row] > prior_high.iloc[row] and regime_return.iloc[row] > 0:
            is_long = True
        elif is_long and (close.iloc[row] < prior_low.iloc[row] or regime_return.iloc[row] <= 0):
            is_long = False
        if is_long and realized.iloc[row] > 0:
            values[row] = min(1.0, TARGET_VOLATILITY / realized.iloc[row])
    return pd.Series(values, index=candles.index, name="target_position")


def return_frame(
    candles: pd.DataFrame,
    target: pd.Series,
    index: pd.DatetimeIndex,
) -> pd.DataFrame:
    target = target.reindex(index)
    position = target.shift(1).fillna(0.0)
    asset = candles["close"].pct_change().reindex(index).fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    gross = position * asset
    cost = turnover * FEE
    return pd.DataFrame(
        {
            "target_position": target,
            "position": position,
            "asset_return": asset,
            "turnover": turnover,
            "gross_strategy_return": gross,
            "trading_cost": cost,
            "strategy_return": gross - cost,
        },
        index=index,
    )


def build_frame(candles: pd.DataFrame, **parameters: int) -> pd.DataFrame:
    index = pd.date_range(START, END, freq="h")
    return return_frame(candles, target_path(candles, **parameters), index)
