from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
ANNUALIZATION = 24 * 365
MOMENTUM_LOOKBACK = 168
REGIME_LOOKBACK = 720
VOLATILITY_LOOKBACK = 168
DECISION_CADENCE_HOURS = 6
TARGET_VOLATILITY = 0.50
TRANSACTION_COST_BPS = 5.0
EVALUATION_START = pd.Timestamp("2023-07-01T00:00:00Z")
EVALUATION_END = pd.Timestamp("2026-06-14T23:00:00Z")
TEST_BARS = 2_160
BLOCK_LENGTH = 168
RESAMPLES = 2_000
CONFIDENCE = 0.95
TAIL_FRACTION = 0.05
CAPACITY_INITIAL_USD = 100_000.0
CAPACITY_PARTICIPATION_LIMIT = 0.001
CAPACITY_LOOKBACK = 720
POSITION_EPSILON = 1e-12

SOURCE = {
    "workflow_run_id": 30069656422,
    "artifact_id": 8587664816,
    "artifact_name": "okx-1h-coverage-488",
    "artifact_sha256": "319123eb2861e6625c9d53953082bcd2fc084f8bb9c1d483d7b4747b6f9d6010",
    "source_head_sha": "a3a4bbf6939873c61ae0eb3bb31bb7b32b258a5e",
    "source_main_sha": "390d98361ccd62b58c18c3999cbcc62287208fdf",
    "coverage_manifest_sha256": "bce56c5ab8581c14f7971075cfa2c5a2dc6dd84a9ea0120a49cbdbad4994a2fc",
    "csv_sha256": {
        "BTC-USDT": "942983ac51f8870c94487ea89ecfabab6cf4a1399c457f3c94cfc89b210d830c",
        "ETH-USDT": "05cfcafd730f0eb5bcb6433a2a725b9b10ebfbd1913c09ca08b84dd5d391ccd9",
    },
}

CANONICAL_SIGNATURE = (
    "cross-sectional-leader-rotation-1h-v1|markets=BTC-USDT,ETH-USDT|"
    "provider=OKX-spot|bar=1H|source=immutable-common-1h-coverage-artifact-8587664816|"
    "architecture=equal-weight-720h-market-regime-plus-168h-relative-strength-leader|"
    "decision-cadence=6h-UTC|position-size=50pct-annual-vol-target-from-prior-168h|"
    "max-gross=1|fee=5bps-one-way|execution=one-complete-bar-delay|"
    "evaluation=2023-07-01T00:00Z..2026-06-14T23:00Z|fold=2160h|"
    "benchmarks=equal-weight-buy-hold,equal-weight-vol-target,equal-weight-720h-trend|"
    "bootstrap=paired-noncircular-168h-blocks-2000-resamples-95pct|"
    "neighbourhood=momentum120,momentum240,cadence3,cadence12|"
    "capacity=USD100000-at-0.10pct-prior-720h-median-hourly-quote-volume|"
    "architecture-candidate-count=1"
)


@dataclass(frozen=True)
class ArchitectureSpec:
    momentum_lookback: int = MOMENTUM_LOOKBACK
    regime_lookback: int = REGIME_LOOKBACK
    volatility_lookback: int = VOLATILITY_LOOKBACK
    decision_cadence_hours: int = DECISION_CADENCE_HOURS
    target_volatility: float = TARGET_VOLATILITY


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_timestamp_strings(values: pd.Series) -> pd.DatetimeIndex:
    raw = values.astype("string")
    explicit = raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if not bool(explicit.all()):
        raise ValueError("timestamps must contain explicit timezone information")
    timestamps = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if timestamps.has_duplicates or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = timestamps[1:] - timestamps[:-1]
        if not bool((intervals == pd.Timedelta(hours=1)).all()):
            raise ValueError("timestamps must have exact one-hour cadence")
    return timestamps


def load_market(artifact_dir: Path, market: str) -> pd.DataFrame:
    if market not in MARKETS:
        raise ValueError(f"unsupported market: {market}")
    path = artifact_dir / market / "snapshot" / f"okx-{market}-1H.csv"
    observed_hash = file_sha256(path)
    if observed_hash != SOURCE["csv_sha256"][market]:
        raise ValueError(
            f"{market} CSV SHA-256 mismatch: expected {SOURCE['csv_sha256'][market]}, "
            f"observed {observed_hash}"
        )
    frame = pd.read_csv(path)
    required = {
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume_base",
        "volume_quote",
        "confirm",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{market} CSV is missing columns: {sorted(missing)}")
    timestamps = _validate_timestamp_strings(frame["timestamp"])
    numeric_columns = ["open", "high", "low", "close", "volume_base", "volume_quote"]
    numeric = frame[numeric_columns].apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy(dtype=float)
    if numeric.isna().any().any() or not np.isfinite(values).all():
        raise ValueError(f"{market} market values must be finite numeric values")
    if (numeric[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{market} OHLC values must be positive")
    if (numeric[["volume_base", "volume_quote"]] < 0).any().any():
        raise ValueError(f"{market} volume values must be non-negative")
    if not (pd.to_numeric(frame["confirm"], errors="coerce") == 1).all():
        raise ValueError(f"{market} source must contain only completed candles")
    validated = numeric.copy()
    validated.index = timestamps
    validated.index.name = "timestamp"
    return validated


def load_source(artifact_dir: str | Path) -> pd.DataFrame:
    root = Path(artifact_dir)
    manifest = root / "coverage-manifest.json"
    observed_manifest_hash = file_sha256(manifest)
    if observed_manifest_hash != SOURCE["coverage_manifest_sha256"]:
        raise ValueError(
            "coverage manifest SHA-256 mismatch: "
            f"expected {SOURCE['coverage_manifest_sha256']}, observed {observed_manifest_hash}"
        )
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    if manifest_payload.get("bar") != "1H" or manifest_payload.get("coverage_complete") is not True:
        raise ValueError("coverage manifest must declare complete 1H coverage")
    economics = manifest_payload.get("economic_boundary")
    if not isinstance(economics, dict) or economics.get("modeled_fee_bps_one_way") != 5.0:
        raise ValueError("coverage manifest must preserve the exact 5 bps economic boundary")
    btc = load_market(root, "BTC-USDT")
    eth = load_market(root, "ETH-USDT")
    if not btc.index.equals(eth.index):
        raise ValueError("BTC-USDT and ETH-USDT timestamps must align exactly")
    frame = pd.DataFrame(index=btc.index)
    frame["btc_close"] = btc["close"]
    frame["btc_volume_quote"] = btc["volume_quote"]
    frame["eth_close"] = eth["close"]
    frame["eth_volume_quote"] = eth["volume_quote"]
    return frame


def _annualized_volatility(close: pd.Series, lookback: int) -> pd.Series:
    log_returns = np.log(close).diff()
    return log_returns.rolling(lookback, min_periods=lookback).std(ddof=0) * math.sqrt(
        ANNUALIZATION
    )


def build_architecture(source: pd.DataFrame, spec: ArchitectureSpec) -> pd.DataFrame:
    close = source[["btc_close", "eth_close"]].copy()
    asset_returns = close.pct_change(fill_method=None).fillna(0.0)
    momentum = close.divide(close.shift(spec.momentum_lookback)).subtract(1.0)
    regime_returns = close.divide(close.shift(spec.regime_lookback)).subtract(1.0)
    broad_regime = regime_returns.mean(axis=1)
    volatility = pd.DataFrame(
        {
            "btc_close": _annualized_volatility(close["btc_close"], spec.volatility_lookback),
            "eth_close": _annualized_volatility(close["eth_close"], spec.volatility_lookback),
        },
        index=source.index,
    )

    target = pd.DataFrame(np.nan, index=source.index, columns=["btc_position", "eth_position"])
    decision_mask = source.index.hour % spec.decision_cadence_hours == 0
    for timestamp in source.index[decision_mask]:
        target.loc[timestamp] = 0.0
        row_momentum = momentum.loc[timestamp]
        row_volatility = volatility.loc[timestamp]
        if (
            not math.isfinite(float(broad_regime.loc[timestamp]))
            or float(broad_regime.loc[timestamp]) <= 0.0
            or row_momentum.isna().any()
            or row_volatility.isna().any()
        ):
            continue
        leader = str(row_momentum.idxmax())
        if float(row_momentum[leader]) <= 0.0:
            continue
        realized_volatility = float(row_volatilityleader])
        if not math.isfinite(realized_volatility) or realized_volatility <= 0.0:
            continue
        size = min(1.0, spec.target_volatility / realized_volatility)
        target_column = "btc_position" if leader == "btc_close" else "eth_position"
        target.loc[timestamp, target_column] = size

    target = target.ffill().fillna(0.0)
    position = target.shift(1).fillna(0.0)
    turnover = position.diff().abs()
    turnover.iloc[0] = position.iloc[0].abs()
    total_turnover = turnover.sum(axis=1)
    gross_return = (
        position["btc_position"] * asset_returns["btc_close"]
        + position["eth_position"] * asset_returns["eth_close"]
    )
    exchange_fee = total_turnover * (TRANSACTION_COST_BPS / 10_000.0)
    net_return = gross_return - exchange_fee

    result = pd.DataFrame(index=source.index)
    result["btc_asset_return"] = asset_returns["btc_close"]
    result["eth_asset_return"] = asset_returns["eth_close"]
    result["btc_target_position"] = target["btc_position"]
    result["eth_target_position"] = target["eth_position"]
    result["btc_position"] = position["btc_position"]
    result["eth_position"] = position["eth_position"]
    result["btc_turnover"] = turnover["btc_position"]
    result["eth_turnover"] = turnover["eth_position"]
    result["turnover"] = total_turnover
    result["gross_return"] = gross_return
    result["exchange_fee"] = exchange_fee
    result["net_return"] = net_return
    result["broad_regime"] = broad_regime
    result["btc_momentum"] = momentum["btc_close"]
    result["eth_momentum"] = momentum["eth_close"]
    return result


def _build_position_path(
    source: pd.DataFrame,
    btc_target: pd.Series,
    eth_target: pd.Series,
) -> pd.DataFrame:
    close = source[["btc_close", "eth_close"]]
    asset_returns = close.pct_change(fill_method=None).fillna(0.0)
    target = pd.DataFrame(
        {"btc_position": btc_target, "eth_position": eth_target},
        index=source.index,
    ).fillna(0.0)
    position = target.shift(1).fillna(0.0)
    turnover = position.diff().abs()
    turnover.iloc[0] = position.iloc[0].abs()
    total_turnover = turnover.sum(axis=1)
    gross = (
        position["btc_position"] * asset_returns["btc_close"]
        + position["eth_position"] * asset_returns["eth_close"]
    )
    fee = total_turnover * (TRANSACTION_COST_BPS / 10_000.0)
    return pd.DataFrame(
        {
            "btc_position": position["btc_position"],
            "eth_position": position["eth_position"],
            "turnover": total_turnover,
            "gross_return": gross,
            "exchange_fee": fee,
            "net_return": gross - fee,
        },
        index=source.index,
    )


def build_benchmarks(source: pd.DataFrame) -> dict[str, pd.DataFrame]:
    index = source.index
    half = pd.Series(0.5, index=index)
    buy_hold = _build_position_path(source, half, half)

    btc_vol = _annualized_volatility(source["btc_close"], VOLATILITY_LOOKBACK)
    eth_vol = _annualized_volatility(source["eth_close"], VOLATILITY_LOOKBACK)
    btc_vol_target = (0.5 * (TARGET_VOLATILITY / btc_vol).clip(upper=1.0)).fillna(0.0)
    eth_vol_target = (0.5 * (TARGET_VOLATILITY / eth_vol).clip(upper=1.0)).fillna(0.0)
    volatility_targeted = _build_position_path(source, btc_vol_target, eth_vol_target)

    btc_trend = (source["btc_close"].divide(source["btc_close"].shift(REGIME_LOOKBACK)) - 1.0)
    eth_trend = (source["eth_close"].divide(source["eth_close"].shift(REGIME_LOOKBACK)) - 1.0)
    simple_trend = _build_position_path(
        source,
        0.5 * (btc_trend > 0.0).astype(float),
        0.5 * (eth_trend > 0.0).astype(float),
    )
    return {
        "equal_weight_buy_and_hold": buy_hold,
        "equal_weight_volatility_targeted_long": volatility_targeted,
        "equal_weight_simple_trend_long_cash": simple_trend,
    }


def evaluation_slice(frame: pd.DataFrame) -> pd.DataFrame:
    evaluated = frame.loc[EVALUATION_START:EVALUATION_END].copy()
    expected = int((EVALUATION_END - EVALUATION_START) / pd.Timedelta(hours=1)) + 1
    if len(evaluated) != expected:
        raise ValueError(f"evaluation window must contain {expected} rows, observed {len(evaluated)}")
    return evaluated


def maximum_drawdown(returns: np.ndarray) -> float:
    nav = np.cumprod(1.0 + np.asarray(returns, dtype=float))
    if nav.size == 0 or not np.isfinite(nav).all() or np.any(nav <= 0.0):
        raise ValueError("returns must produce a finite positive NAV")
    peaks = np.maximum.accumulate(np.concatenate(([1.0], nav)))
    drawdowns = np.concatenate(([1.0], nav)) / peaks - 1.0
    return float(drawdowns.min())


def performance_metrics(returns: pd.Series | np.ndarray, turnover: pd.Series | np.ndarray | None = None) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise ValueError("returns must be a non-empty finite vector")
    nav = np.cumprod(1.0 + values)
    if np.any(nav <= 0.0) or not np.isfinite(nav).all():
        raise ValueError("returns must preserve positive finite capital")
    total_return = float(nav[-1] - 1.0)
    cagr = float(nav[-1] ** (ANNUALIZATION / values.size) - 1.0)
    mean = float(values.mean())
    std = float(values.std(ddof=0))
    sharpe = float(math.sqrt(ANNUALIZATION) * mean / std) if std > 0 else 0.0
    downside = np.minimum(values, 0.0)
    downside_deviation = float(math.sqrt(np.mean(downside ** 2)))
    sortino = (
        float(math.sqrt(ANNUALIZATION) * mean / downside_deviation)
        if downside_deviation > 0
        else 0.0
    )
    max_dd = maximum_drawdown(values)
    calmar = float(cagr / abs(max_dd)) if max_dd < 0 else 0.0
    metrics = {
        "total_return": total_return,
        "cagr": cagr,
        "annualized_arithmetic_mean": mean * ANNUALIZATION,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "maximum_drawdown": max_dd,
    }
    if turnover is not None:
        turn = np.asarray(turnover, dtype=float)
        if turn.shape != values.shape or not np.isfinite(turn).all() or np.any(turn < 0.0):
            raise ValueError("turnover must be a finite non-negative vector aligned with returns")
        metrics["annualized_turnover"] = float(turn.sum() * ANNUALIZATION / values.size)
    return metrics


def expected_shortfall(returns: pd.Series | np.ndarray, fraction: float = TAIL_FRACTION) -> float:
    values = np.sort(np.asarray(returns, dtype=float))
    tail_count = max(1, math.ceil(values.size * fraction))
    return float(values[:tail_count].mean())


def fold_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    if len(frame) % TEST_BARS != 0:
        raise ValueError("evaluation window must contain complete 2160-hour folds")
    fold_returns: list[float] = []
    for start in range(0, len(frame), TEST_BARS):
        values = frame["net_return"].iloc[start : start + TEST_BARS].to_numpy(dtype=float)
        fold_returns.append(float(np.prod(1.0 + values) - 1.0))
    positive = [value for value in fold_returns if value > 0.0]
    positive_sum = sum(positive)
    concentration = max(positive) / positive_sum if positive_sum > 0.0 else 1.0
    return {
        "fold_count": len(fold_returns),
        "profitable_folds": len(positive),
        "best_fold_return": max(fold_returns),
        "worst_fold_return": min(fold_returns),
        "largest_positive_fold_contribution": concentration,
        "fold_returns": fold_returns,
    }


def _complete_month(index: pd.DatetimeIndex) -> bool:
    start = index[0].normalize().replace(day=1)
    end = (start + pd.offsets.MonthEnd(1)).replace(hour=23)
    expected = int((end - start) / pd.Timedelta(hours=1)) + 1
    return index[0] == start and index[-1] == end and len(index) == expected


def _complete_year(index: pd.DatetimeIndex) -> bool:
    year = int(index[0].year)
    start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
    end = pd.Timestamp(year=year, month=12, day=31, hour=23, tz="UTC")
    expected = int((end - start) / pd.Timedelta(hours=1)) + 1
    return index[0] == start and index[-1] == end and len(index) == expected


def calendar_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    series = frame["net_return"]
    months: list[dict[str, Any]] = []
    month_keys = pd.MultiIndex.from_arrays([series.index.year, series.index.month])
    for (year, month), group in series.groupby(_month_keys):
        complete = _complete_month(pd.DatetimeIndex(group.index))
        months.append(
            {
                "period": f"{int(year)}{0int(month)}:02d}",
                "complete": complete,
                "return": float(np.prod(1.0 + group.to_numpy(dtype=float)) - 1.0),
            }
        )
    years: list[dict[str, Any]] = []
    for year, group in series.groupby(series.index.year):
        complete = _complete_year(pd.DatetimeIndex(group.index))
        years.append(
            {
                "year": int(year),
                "complete": complete,
                "return": float(np.prod(1.0 + group.to_numpy(dtype=float)) - 1.0),
            }
        )
    complete_months = [item for item in months if item["complete"]]
    complete_years = [item for item in years if item["complete"]]
    return {
        "months": months,
        "complete_months": len(complete_months),
        "profitable_complete_months": sum(item["return"] > 0.0 for item in complete_months),
        "years": years,
        "complete_years": len(complete_years),
        "profitable_complete_years": sum(item["return"] > 0.0 for item in complete_years),
    }


def activity_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    active = (frame[["btc_position", "eth_position"]].abs().sum(axis=1) > POSITION_EPSILON)
    starts = active & ~active.shift(1, fill_value=False)
    exits = ~active & active.shift(1, fill_value=False)
    start_positions = list(np.flatnonzero(starts.to_numpy()))
    exit_positions = list(np.flatnonzero(exits.to_numpy()))
    completed_returns: list[float] = []
    holding_hours: list[int] = []
    exit_cursor = 0
    for start in start_positions:
        while exit_cursor < len(exit_positions) and exit_positions[exit_cursor] <= start:
            exit_cursor += 1
        if exit_cursor >= len(exit_positions):
            continue
        exit_row = exit_positions[exit_cursor]
        values = frame["net_return"].iloc[start : exit_row + 1].to_numpy(dtype=float)
        completed_returns.append(float(np.prod(1.0 + values) - 1.0))
        holding_hours.append(int(exit_row - start))
        exit_cursor += 1
    years = len(frame) / ANNUALIZATION
    positives = sum(value > 0.0 for value in completed_returns)
    gains = sum(value for value in completed_returns if value > 0.0)
    losses = -sum(value for value in completed_returns if value < 0.0)
    profit_factor = gains / losses if losses > 0.0 else math.inf
    adjustments = int((frame["turnover"] > POSITION_EPSILON).sum())
    leader_switches = int(
        (
            frame[["btc_position", "eth_position"]].idxmax(axis=1)
            != frame[["btc_position", "eth_position"]].idxmax(axis=1).shift(1)
        ).sum()
    )
    return {
        "position_adjustment_observations": adjustments,
        "annualized_position_adjustments": adjustments / years,
        "completed_exposure_episodes": len(completed_returns),
        "annualized_completed_episodes": len(completed_returns) / years,
        "median_holding_hours": float(np.median(holding_hours)) if holding_hours else 0.0,
        "mean_holding_hours": float(np.mean(holding_hours)) if holding_hours else 0.0,
        "maximum_holding_hours": max(holding_hours, default=0),
        "completed_episode_hit_rate": positives / len(completed_returns) if completed_returns else 0.0,
        "completed_episode_profit_factor": float(profit_factor),
        "leader_state_changes": leader_switches,
    }


def capacity_statistics(source: pd.DataFrame, frame: pd.DataFrame) -> dict[str, Any]:
    full_nav = (1.0 + frame["net_return"]).cumprod()
    prior_nav = full_nav.shift(1).fillna(1.0)
    liquidity = pd.DataFrame(
        {
            "btc": source["btc_volume_quote"].rolling(CAPACITY_LOOKBACK).median().shift(1),
            "eth": source["eth_volume_quote"].rolling(CAPACITY_LOOKBACK).median().shift(1),
        },
        index=source.index,
    )
    records: list[float] = []
    supported_capitals: list[float] = []
    for asset in ("btc", "eth"):
        turnover = frame[f"{asset}_turnover"]
        adjustment = turnover > POSITION_EPSILON
        notional_per_initial_dollar = turnover[adjustment] * prior_nav[adjustment]
        adjustment_index = adjustment.index[adjustment]
        lagged_liquidity = liquidity.loc[adjustment_index, asset]
        valid = lagged_liquidity.notna() & (lagged_liquidity > 0.0)
        notional_per_initial_dollar = notional_per_initial_dollar.loc[valid.index]
        participation = (
            notional_per_initial_dollar[valid] * CAPACITY_INITIAL_USD / lagged_liquidity[valid]
        )
        records.extend(participation.tolist())
        supported = (
            CAPACITY_PARTICIPATION_LIMIT
            * lagged_liquidity[valid]
            / notional_per_initial_dollar[valid]
        )
        supported_capitals.extend(supported.tolist())
    array = np.asarray(records, dtype=float)
    if array.size == 0:
        raise ValueError("capacity evaluation requires position adjustments")
    return {
        "initial_capital_usd": CAPACITY_INITIAL_USD,
        "participation_limit": CAPACITY_PARTICIPATION_LIMIT,
        "adjustment_components": int(array.size),
        "breach_components": int((array > CAPACITY_PARTICIPATION_LIMIT).sum()),
        "breach_share": float((array > CAPACITY_PARTICIPATION_LIMIT).mean()),
        "median_participation": float(np.median(array)),
        "p95_participation": float(np.quantile(array, 0.95)),
        "maximum_participation": float(array.max()),
        "maximum_supported_initial_capital_usd": float(min(supported_capitals)),
    }


def _bootstrap_indices(rng: np.random.Generator, length: int, block: int) -> np.ndarray:
    blocks = math.ceil(length / block)
    starts = rng.integers(0, length - block + 1, size=blocks)
    return np.concatenate([nMÄ