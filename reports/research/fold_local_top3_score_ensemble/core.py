from __future__ import annotations

import hashlib
import itertools
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
MOMENTUM_LOOKBACKS = (30, 90, 180)
REVERSAL_LOOKBACKS = (2, 5, 10)
TREND_WEIGHTS = (0.55, 0.70, 0.85)
VOLATILITY_LOOKBACK = 30
TARGET_VOLATILITY = 0.50
MAX_POSITION = 1.0
MIN_POSITION = 0.0
BASELINE_COST_BPS = 5.0
ALL_IN_COSTS_BPS = (5.0, 7.5, 10.0, 15.0)
ANNUALIZATION = 365
SELECTION_BARS = 730
TEST_BARS = 90
TOP_K = 3
NEIGHBOUR_TOP_K = (2, 4)
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
BENCHMARK_SEEDS = {"BTC-USDT": 2026072406, "ETH-USDT": 2026072407}
ADAPTIVE_SEEDS = {"BTC-USDT": 2026072416, "ETH-USDT": 2026072417}
DELAY_SEED_BASE = {"BTC-USDT": 2026072450, "ETH-USDT": 2026072470}
EXPECTED_EVALUATION_START = pd.Timestamp("2020-01-11T00:00:00Z")
EXPECTED_EVALUATION_END = pd.Timestamp("2026-07-22T00:00:00Z")
EXPECTED_OBSERVATIONS = 2_385
SOURCE = {
    "workflow_run_id": 30040842607,
    "artifact_id": 8577163034,
    "artifact_name": "quant-research-source-348-attempt-1",
    "artifact_sha256": "a06f20584f243c4db1420e8ed0b6cacdc13eb11aebddefb72c30cc80176ccd45",
    "source_head_sha": "eea39bc685246209cdb6c0d917fddcc6ef29f34b",
}
EXPECTED_HASHES = {
    "BTC-USDT": {
        "snapshot": "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1",
        "returns": "04a0a5257d1e20f1eb88c70b8a0b010d21f0dc35ccb657ba39f14189e9f20790",
    },
    "ETH-USDT": {
        "snapshot": "842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f",
        "returns": "4b69db4a44644a5f830e1518aca93356c0eeacf502dc00ba990bd992b9bd387f",
    },
}
CANONICAL_SIGNATURE = (
    "fold-local-top3-score-ensemble-v1|markets=BTC-USDT,ETH-USDT|"
    "source=verified-OKX-1Dutc-snapshots-and-canonical-5bps-returns|"
    "development-markets-only=true|grid=momentum30,90,180-reversal2,5,10-"
    "trend0.55,0.70,0.85|selection=canonical-score-ranked-within-prior-730-bars|"
    "architecture=equal-weight-mean-of-top3-one-bar-delayed-candidate-positions|"
    "test=nonoverlapping-90-bars-continuous-aggregate-position|fee=5bps-one-way|"
    "all-in-cost-stress=5,7.5,10,15bps-fixed-path|neighbourhood=top2,top4|"
    "delay-stress=total-delay-2,3-bars-at-all-costs|benchmark=volatility-targeted-long|"
    "inference=paired-noncircular-moving-block-bootstrap-20-resamples2000-confidence0.95|"
    "claim=all-BTC-ETH-development-freeze-gates-pass|candidate_count=1"
)
_TIMEZONE_PATTERN = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_grid() -> list[tuple[int, int, float]]:
    return list(itertools.product(MOMENTUM_LOOKBACKS, REVERSAL_LOOKBACKS, TREND_WEIGHTS))


def _validated_timestamps(values: pd.Series) -> pd.DatetimeIndex:
    raw = values.astype("string")
    if not bool(raw.str.contains(_TIMEZONE_PATTERN, na=False).all()):
        raise ValueError("timestamps must include an explicit timezone offset")
    timestamps = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        cadence = timestamps[1:] - timestamps[:-1]
        if not bool((cadence == pd.Timedelta(days=1)).all()):
            raise ValueError("timestamps must have exact daily cadence")
    return timestamps


def load_snapshot(path: str | Path, market: str, *, verify_hash: bool = True) -> pd.Series:
    snapshot_path = Path(path)
    if market not in EXPECTED_HASHES:
        raise ValueError(f"unsupported market: {market}")
    if verify_hash:
        observed = file_sha256(snapshot_path)
        expected = EXPECTED_HASHES[market]["snapshot"]
        if observed != expected:
            raise ValueError(
                f"{market} snapshot SHA-256 mismatch: expected {expected}, observed {observed}"
            )
    frame = pd.read_csv(snapshot_path)
    required = {"timestamp", "close", "confirm"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"snapshot is missing required columns: {sorted(missing)}")
    timestamps = _validated_timestamps(frame["timestamp"])
    close = pd.to_numeric(frame["close"], errors="coerce")
    confirm = pd.to_numeric(frame["confirm"], errors="coerce")
    if close.isna().any() or not np.isfinite(close.to_numpy(dtype=float)).all():
        raise ValueError("snapshot close values must be finite")
    if (close <= 0.0).any():
        raise ValueError("snapshot close values must be strictly positive")
    if confirm.isna().any() or not bool(confirm.eq(1).all()):
        raise ValueError("snapshot must contain confirmed candles only")
    return pd.Series(close.to_numpy(dtype=float), index=timestamps, name="close")


def load_canonical_returns(
    path: str | Path,
    market: str,
    *,
    verify_hash: bool = True,
) -> pd.DataFrame:
    returns_path = Path(path)
    if market not in EXPECTED_HASHES:
        raise ValueError(f"unsupported market: {market}")
    if verify_hash:
        observed = file_sha256(returns_path)
        expected = EXPECTED_HASHES[market]["returns"]
        if observed != expected:
            raise ValueError(
                f"{market} return SHA-256 mismatch: expected {expected}, observed {observed}"
            )
    frame = pd.read_csv(returns_path)
    required = {
        "timestamp",
        "strategy_return",
        "benchmark_volatility_targeted_long_return",
        "fold",
    }
    missing = required - set(frame)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")
    timestamps = _validated_timestamps(frame["timestamp"])
    validated = pd.DataFrame({"timestamp": timestamps})
    for column in required - {"timestamp"}:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
            raise ValueError(f"{column} must contain only finite values")
        validated[column] = numeric.to_numpy(dtype=float)
    if len(validated) != EXPECTED_OBSERVATIONS:
        raise ValueError(f"expected {EXPECTED_OBSERVATIONS} OOS observations")
    if validated["timestamp"].iloc[0] != EXPECTED_EVALUATION_START:
        raise ValueError("unexpected evaluation start")
    if validated["timestamp"].iloc[-1] != EXPECTED_EVALUATION_END:
        raise ValueError("unexpected evaluation end")
    return_columns = validated[
        ["strategy_return", "benchmark_volatility_targeted_long_return"]
    ]
    if (return_columns <= -1.0).any().any():
        raise ValueError("returns must remain greater than -100%")
    return validated.set_index("timestamp")


def build_target_position(
    prices: pd.Series,
    *,
    momentum_lookback: int,
    reversal_lookback: int,
    trend_weight: float,
) -> pd.Series:
    log_returns = np.log(prices).diff()
    trend_mean = log_returns.rolling(momentum_lookback, min_periods=momentum_lookback).mean()
    trend_std = log_returns.rolling(momentum_lookback, min_periods=momentum_lookback).std(ddof=0)
    trend_score = trend_mean / trend_std.replace(0.0, np.nan) * math.sqrt(momentum_lookback)
    recent_return = log_returns.rolling(reversal_lookback, min_periods=reversal_lookback).sum()
    risk_scale = log_returns.rolling(
        VOLATILITY_LOOKBACK,
        min_periods=VOLATILITY_LOOKBACK,
    ).std(ddof=0)
    reversal_score = -recent_return / (
        risk_scale.replace(0.0, np.nan) * math.sqrt(reversal_lookback)
    )
    ensemble_score = (
        trend_weight * trend_score + (1.0 - trend_weight) * reversal_score
    ).clip(-4.0, 4.0)
    directional_signal = pd.Series(
        np.tanh(ensemble_score.to_numpy(dtype=float)),
        index=ensemble_score.index,
    )
    realized_volatility = risk_scale * math.sqrt(ANNUALIZATION)
    volatility_scalar = (TARGET_VOLATILITY / realized_volatility.replace(0.0, np.nan)).clip(
        lower=0.0,
        upper=MAX_POSITION,
    )
    target = (directional_signal * volatility_scalar).clip(MIN_POSITION, MAX_POSITION)
    return target.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def candidate_frame(prices: pd.Series, candidate: tuple[int, int, float]) -> pd.DataFrame:
    momentum, reversal, trend_weight = candidate
    target = build_target_position(
        prices,
        momentum_lookback=momentum,
        reversal_lookback=reversal,
        trend_weight=trend_weight,
    )
    position = target.shift(1).fillna(0.0)
    asset_return = prices.pct_change().fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    gross = position * asset_return
    cost = turnover * BASELINE_COST_BPS / 10_000.0
    return pd.DataFrame(
        {
            "asset_return": asset_return,
            "target_position": target,
            "position": position,
            "turnover": turnover,
            "gross_strategy_return": gross,
            "trading_cost": cost,
            "strategy_return": gross - cost,
        },
        index=prices.index,
    )


def _rebased_window(frame: pd.DataFrame, previous_position: float, cost_bps: float) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        raise ValueError("window cannot be empty")
    result.iloc[0, result.columns.get_loc("turnover")] = abs(
        float(result["position"].iloc[0]) - previous_position
    )
    result.iloc[0, result.columns.get_loc("trading_cost")] = (
        float(result["turnover"].iloc[0]) * cost_bps / 10_000.0
    )
    result.iloc[0, result.columns.get_loc("strategy_return")] = (
        float(result["gross_strategy_return"].iloc[0])
        - float(result["trading_cost"].iloc[0])
    )
    return result
