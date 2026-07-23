from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

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
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
BENCHMARK_SEEDS = {"BTC-USDT": 2026072408, "ETH-USDT": 2026072409}
ADAPTIVE_SEEDS = {"BTC-USDT": 2026072418, "ETH-USDT": 2026072419}
DELAY_SEED_BASE = {"BTC-USDT": 2026072480, "ETH-USDT": 2026072490}
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
    "cross-market-maximin-shared-candidate-v1|markets=BTC-USDT,ETH-USDT|"
    "source=verified-OKX-1Dutc-snapshots-and-canonical-5bps-returns|"
    "development-markets-only=true|grid=momentum30,90,180-reversal2,5,10-"
    "trend0.55,0.70,0.85|selection=one-shared-candidate-per-fold-maximizing-"
    "minimum-canonical-score-across-BTC-ETH-prior-730-bars|test=separate-"
    "nonoverlapping-90-bar-market-paths-continuous-position|fee=5bps-one-way|"
    "all-in-cost-stress=5,7.5,10,15bps-fixed-path|neighbourhood=mean-score,rank-sum|"
    "delay-stress=total-delay-2,3-bars-at-all-costs|benchmark=volatility-targeted-long|"
    "inference=paired-noncircular-moving-block-bootstrap-20-resamples2000-"
    "confidence0.95|claim=all-BTC-ETH-development-freeze-gates-pass|candidate_count=1"
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
    return_columns = validated[["strategy_return", "benchmark_volatility_targeted_long_return"]]
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
    trend_mean = log_returns.rolling(
        momentum_lookback,
        min_periods=momentum_lookback,
    ).mean()
    trend_std = log_returns.rolling(
        momentum_lookback,
        min_periods=momentum_lookback,
    ).std(ddof=0)
    trend_score = trend_mean / trend_std.replace(0.0, np.nan) * math.sqrt(momentum_lookback)
    recent_return = log_returns.rolling(
        reversal_lookback,
        min_periods=reversal_lookback,
    ).sum()
    risk_scale = log_returns.rolling(
        VOLATILITY_LOOKBACK,
        min_periods=VOLATILITY_LOOKBACK,
    ).std(ddof=0)
    reversal_score = -recent_return / (
        risk_scale.replace(0.0, np.nan) * math.sqrt(reversal_lookback)
    )
    ensemble_score = (trend_weight * trend_score + (1.0 - trend_weight) * reversal_score).clip(
        -4.0, 4.0
    )
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
    trading_cost = turnover * BASELINE_COST_BPS / 10_000.0
    return pd.DataFrame(
        {
            "asset_return": asset_return,
            "target_position": target,
            "position": position,
            "turnover": turnover,
            "gross_strategy_return": gross,
            "trading_cost": trading_cost,
            "strategy_return": gross - trading_cost,
        },
        index=prices.index,
    )


def _rebased_window(
    frame: pd.DataFrame,
    previous_position: float,
    cost_bps: float,
) -> pd.DataFrame:
    result = frame.copy()
    if result.empty:
        raise ValueError("window cannot be empty")
    result.iloc[0, result.columns.get_loc("turnover")] = abs(
        float(result["position"].iloc[0]) - previous_position
    )
    result.iloc[0, result.columns.get_loc("trading_cost")] = (
        float(result["turnover"].iloc[0]) * cost_bps / 10_000.0
    )
    result.iloc[0, result.columns.get_loc("strategy_return")] = float(
        result["gross_strategy_return"].iloc[0]
    ) - float(result["trading_cost"].iloc[0])
    return result


def return_metrics(returns: pd.Series | np.ndarray) -> dict[str, float | int]:
    values = np.asarray(returns, dtype=float)
    if values.size == 0 or not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("returns must be finite, non-empty, and greater than -1")
    observations = int(values.size)
    growth = float(np.prod(1.0 + values))
    total_return = growth - 1.0
    cagr = growth ** (ANNUALIZATION / observations) - 1.0 if growth > 0.0 else -1.0
    mean = float(values.mean())
    standard_deviation = float(values.std(ddof=0))
    annualized_mean = mean * ANNUALIZATION
    annualized_volatility = standard_deviation * math.sqrt(ANNUALIZATION)
    sharpe = (
        mean / standard_deviation * math.sqrt(ANNUALIZATION) if standard_deviation > 0.0 else 0.0
    )
    downside = np.minimum(values, 0.0)
    downside_deviation = float(np.sqrt(np.mean(np.square(downside))))
    sortino = (
        mean / downside_deviation * math.sqrt(ANNUALIZATION) if downside_deviation > 0.0 else 0.0
    )
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    drawdown = nav / np.maximum.accumulate(nav) - 1.0
    max_drawdown = float(drawdown.min())
    calmar = cagr / abs(max_drawdown) if max_drawdown < 0.0 else 0.0
    return {
        "observations": observations,
        "total_return": total_return,
        "cagr": cagr,
        "annualized_arithmetic_mean": annualized_mean,
        "annualized_volatility": annualized_volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
    }


def frame_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    values = return_metrics(frame["strategy_return"])
    values.update(
        {
            "annualized_turnover": float(frame["turnover"].mean()) * ANNUALIZATION,
            "average_abs_exposure": float(frame["position"].abs().mean()),
            "exchange_fee_sum": float(frame["trading_cost"].sum()),
        }
    )
    return values


def selection_score(metrics: dict[str, float | int]) -> float:
    return (
        float(metrics["sharpe"])
        + 0.20 * float(metrics["calmar"])
        - 0.50 * abs(float(metrics["max_drawdown"]))
        - 0.01 * float(metrics["annualized_turnover"])
    )


def aggregate_shared_scores(scores: dict[str, float], rule: str) -> float:
    if set(scores) != set(MARKETS):
        raise ValueError("shared scores must contain exactly the declared development markets")
    values = np.asarray([scores[market] for market in MARKETS], dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("shared scores must be finite")
    if rule == "maximin":
        return float(values.min())
    if rule == "mean_score":
        return float(values.mean())
    raise ValueError(f"unsupported shared-score rule: {rule}")


def build_shared_path(
    prices: dict[str, pd.Series],
    *,
    rule: str,
    cost_bps: float = BASELINE_COST_BPS,
) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]]]:
    if set(prices) != set(MARKETS):
        raise ValueError("prices must contain exactly the declared development markets")
    common_index = prices[MARKETS[0]].index
    if any(not prices[market].index.equals(common_index) for market in MARKETS[1:]):
        raise ValueError("development markets must have identical timestamps")

    grid = candidate_grid()
    cached = {
        market: {candidate: candidate_frame(prices[market], candidate) for candidate in grid}
        for market in MARKETS
    }
    previous_position = {market: 0.0 for market in MARKETS}
    frames: dict[str, list[pd.DataFrame]] = {market: [] for market in MARKETS}
    fold_records: list[dict[str, Any]] = []

    for fold, test_start_index in enumerate(
        range(SELECTION_BARS, len(common_index), TEST_BARS),
        start=1,
    ):
        test_end_index = min(test_start_index + TEST_BARS, len(common_index)) - 1
        if test_end_index - test_start_index + 1 < max(20, TEST_BARS // 2):
            break
        selection_end_index = test_start_index - 1
        selection_start_index = selection_end_index - SELECTION_BARS + 1
        selection_start = common_index[selection_start_index]
        selection_end = common_index[selection_end_index]
        test_start = common_index[test_start_index]
        test_end = common_index[test_end_index]

        scored: list[dict[str, Any]] = []
        per_market_rank_inputs: dict[str, list[tuple[float, tuple[int, int, float]]]] = {
            market: [] for market in MARKETS
        }
        for candidate in grid:
            scores: dict[str, float] = {}
            for market in MARKETS:
                window = _rebased_window(
                    cached[market][candidate].loc[selection_start:selection_end],
                    0.0,
                    BASELINE_COST_BPS,
                )
                score = selection_score(frame_metrics(window))
                if not math.isfinite(score):
                    raise RuntimeError("every declared candidate must produce a finite score")
                scores[market] = score
                per_market_rank_inputs[market].append((score, candidate))
            scored.append(
                {
                    "candidate": candidate,
                    "market_scores": scores,
                    "aggregate_score": aggregate_shared_scores(scores, rule)
                    if rule != "rank_sum"
                    else 0.0,
                }
            )

        if rule == "rank_sum":
            ranks: dict[str, dict[tuple[int, int, float], int]] = {}
            for market in MARKETS:
                ordered = sorted(
                    per_market_rank_inputs[market],
                    key=lambda item: (item[0], item[1]),
                    reverse=True,
                )
                ranks[market] = {
                    candidate: rank for rank, (_, candidate) in enumerate(ordered, start=1)
                }
            for item in scored:
                candidate = item["candidate"]
                item["market_ranks"] = {market: ranks[market][candidate] for market in MARKETS}
                item["aggregate_score"] = -float(
                    sum(ranks[market][candidate] for market in MARKETS)
                )
        elif rule not in {"maximin", "mean_score"}:
            raise ValueError(f"unsupported shared-score rule: {rule}")

        scored.sort(
            key=lambda item: (item["aggregate_score"], item["candidate"]),
            reverse=True,
        )
        selected = scored[0]
        candidate = selected["candidate"]
        fold_record: dict[str, Any] = {
            "fold": fold,
            "selection_start": selection_start.isoformat(),
            "selection_end": selection_end.isoformat(),
            "test_start": test_start.isoformat(),
            "test_end": test_end.isoformat(),
            "candidates_tested": len(scored),
            "selected": {
                "momentum_lookback": int(candidate[0]),
                "reversal_lookback": int(candidate[1]),
                "trend_weight": float(candidate[2]),
            },
            "aggregate_score": float(selected["aggregate_score"]),
            "market_scores": {
                market: float(selected["market_scores"][market]) for market in MARKETS
            },
        }
        if "market_ranks" in selected:
            fold_record["market_ranks"] = selected["market_ranks"]

        for market in MARKETS:
            frame = _rebased_window(
                cached[market][candidate].loc[test_start:test_end],
                previous_position[market],
                cost_bps,
            )
            frame = frame.copy()
            frame["fold"] = fold
            frames[market].append(frame)
            previous_position[market] = float(frame["position"].iloc[-1])
        fold_records.append(fold_record)

    combined = {market: pd.concat(frames[market]).sort_index() for market in MARKETS}
    if any(frame.index.has_duplicates for frame in combined.values()):
        raise RuntimeError("test folds must not overlap")
    return combined, fold_records


def reprice(frame: pd.DataFrame, cost_bps: float) -> pd.DataFrame:
    result = frame.copy()
    result["trading_cost"] = result["turnover"] * cost_bps / 10_000.0
    result["strategy_return"] = result["gross_strategy_return"] - result["trading_cost"]
    return result


def delay_path(frame: pd.DataFrame, total_delay_bars: int, cost_bps: float) -> pd.DataFrame:
    if total_delay_bars < 1:
        raise ValueError("total_delay_bars must be at least one")
    position = frame["position"].shift(total_delay_bars - 1).fillna(0.0)
    turnover = position.diff().abs()
    turnover.iloc[0] = abs(float(position.iloc[0]))
    gross = position * frame["asset_return"]
    trading_cost = turnover * cost_bps / 10_000.0
    return pd.DataFrame(
        {
            "asset_return": frame["asset_return"],
            "position": position,
            "turnover": turnover,
            "gross_strategy_return": gross,
            "trading_cost": trading_cost,
            "strategy_return": gross - trading_cost,
            "fold": frame["fold"],
        },
        index=frame.index,
    )


def fold_stability(frame: pd.DataFrame) -> dict[str, Any]:
    records = [
        {
            "fold": int(fold),
            "return": float((1.0 + group["strategy_return"]).prod() - 1.0),
        }
        for fold, group in frame.groupby("fold", sort=True)
    ]
    positive = [record["return"] for record in records if record["return"] > 0.0]
    positive_total = sum(positive)
    concentration = max(positive) / positive_total if positive_total > 0.0 else 1.0
    minimum_profitable = math.ceil(len(records) / 2)
    passes = len(positive) >= minimum_profitable and concentration <= 0.50
    return {
        "records": records,
        "fold_count": len(records),
        "profitable_folds": len(positive),
        "positive_fold_ratio": len(positive) / len(records),
        "best_fold_total_return": max(record["return"] for record in records),
        "worst_fold_total_return": min(record["return"] for record in records),
        "max_positive_fold_share": concentration,
        "minimum_profitable_folds": minimum_profitable,
        "maximum_allowed_positive_fold_share": 0.50,
        "passes": passes,
        "failure_reasons": []
        if passes
        else [
            reason
            for condition, reason in (
                (
                    len(positive) < minimum_profitable,
                    "fewer than half of OOS folds are profitable",
                ),
                (
                    concentration > 0.50,
                    "one fold contributes more than half of positive fold return",
                ),
            )
            if condition
        ],
    }


def calendar_stability(frame: pd.DataFrame) -> dict[str, Any]:
    returns = frame["strategy_return"]
    years: list[dict[str, Any]] = []
    for year, group in returns.groupby(returns.index.year, sort=True):
        years.append(
            {
                "year": int(year),
                "return": float((1.0 + group).prod() - 1.0),
                "partial": not (
                    group.index[0].month == 1
                    and group.index[0].day == 1
                    and group.index[-1].month == 12
                    and group.index[-1].day == 31
                ),
            }
        )
    complete = [record for record in years if not record["partial"]]
    profitable = sum(record["return"] > 0.0 for record in complete)
    ratio = profitable / len(complete) if complete else 0.0
    minimum_return = min((record["return"] for record in complete), default=-math.inf)
    passes = len(complete) >= 4 and ratio >= 0.60 and minimum_return > -0.20
    return {
        "years": years,
        "completed_year_count": len(complete),
        "profitable_completed_years": profitable,
        "profitable_completed_year_ratio": ratio,
        "minimum_complete_year_return": minimum_return,
        "passes": passes,
    }


def expected_shortfall_5pct(returns: pd.Series | np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    count = math.ceil(0.05 * len(values))
    return float(np.sort(values)[:count].mean())


def noncircular_block_indices(
    observations: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    blocks_needed = math.ceil(observations / block_length)
    starts = rng.integers(0, observations - block_length + 1, size=blocks_needed)
    return np.concatenate([np.arange(start, start + block_length) for start in starts])[
        :observations
    ]


def paired_metric_delta_bootstrap(
    candidate: pd.Series,
    comparator: pd.Series,
    *,
    seed: int,
) -> dict[str, Any]:
    candidate_values = candidate.to_numpy(dtype=float)
    comparator_values = comparator.to_numpy(dtype=float)
    if candidate_values.shape != comparator_values.shape:
        raise ValueError("paired returns must have identical shapes")
    rng = np.random.default_rng(seed)
    sharpe_deltas = np.empty(RESAMPLES)
    calmar_deltas = np.empty(RESAMPLES)
    for resample in range(RESAMPLES):
        indices = noncircular_block_indices(len(candidate_values), BLOCK_LENGTH, rng)
        candidate_metrics = return_metrics(candidate_values[indices])
        comparator_metrics = return_metrics(comparator_values[indices])
        sharpe_deltas[resample] = float(candidate_metrics["sharpe"]) - float(
            comparator_metrics["sharpe"]
        )
        calmar_deltas[resample] = float(candidate_metrics["calmar"]) - float(
            comparator_metrics["calmar"]
        )
    alpha = (1.0 - CONFIDENCE) / 2.0
    candidate_metrics = return_metrics(candidate_values)
    comparator_metrics = return_metrics(comparator_values)
    return {
        "sharpe_delta": {
            "point": float(candidate_metrics["sharpe"]) - float(comparator_metrics["sharpe"]),
            "lower": float(np.quantile(sharpe_deltas, alpha)),
            "upper": float(np.quantile(sharpe_deltas, 1.0 - alpha)),
            "probability_positive": float(np.mean(sharpe_deltas > 0.0)),
        },
        "calmar_delta": {
            "point": float(candidate_metrics["calmar"]) - float(comparator_metrics["calmar"]),
            "lower": float(np.quantile(calmar_deltas, alpha)),
            "upper": float(np.quantile(calmar_deltas, 1.0 - alpha)),
            "probability_positive": float(np.mean(calmar_deltas > 0.0)),
        },
    }


def absolute_return_bootstrap(returns: pd.Series, *, seed: int) -> dict[str, Any]:
    values = returns.to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    annualized_means = np.empty(RESAMPLES)
    sharpes = np.empty(RESAMPLES)
    for resample in range(RESAMPLES):
        indices = noncircular_block_indices(len(values), BLOCK_LENGTH, rng)
        metrics = return_metrics(values[indices])
        annualized_means[resample] = float(metrics["annualized_arithmetic_mean"])
        sharpes[resample] = float(metrics["sharpe"])
    alpha = (1.0 - CONFIDENCE) / 2.0
    return {
        "annualized_arithmetic_mean": {
            "lower": float(np.quantile(annualized_means, alpha)),
            "upper": float(np.quantile(annualized_means, 1.0 - alpha)),
            "probability_positive": float(np.mean(annualized_means > 0.0)),
        },
        "sharpe": {
            "lower": float(np.quantile(sharpes, alpha)),
            "upper": float(np.quantile(sharpes, 1.0 - alpha)),
            "probability_positive": float(np.mean(sharpes > 0.0)),
        },
    }


def _compact_metrics(metrics: dict[str, float | int]) -> dict[str, float | int]:
    keys = ("total_return", "sharpe", "max_drawdown", "annualized_turnover")
    return {key: metrics[key] for key in keys}


def analyze_market(
    market: str,
    candidate: pd.DataFrame,
    canonical: pd.DataFrame,
    neighbourhoods: dict[str, pd.DataFrame],
    fold_records: list[dict[str, Any]],
) -> dict[str, Any]:
    benchmark = canonical["benchmark_volatility_targeted_long_return"]
    adaptive = canonical["strategy_return"]
    benchmark_bootstrap = paired_metric_delta_bootstrap(
        candidate["strategy_return"],
        benchmark,
        seed=BENCHMARK_SEEDS[market],
    )
    adaptive_bootstrap = paired_metric_delta_bootstrap(
        candidate["strategy_return"],
        adaptive,
        seed=ADAPTIVE_SEEDS[market],
    )
    cost_scenarios = {
        f"{cost_bps:g}": _compact_metrics(frame_metrics(reprice(candidate, cost_bps)))
        for cost_bps in ALL_IN_COSTS_BPS
    }
    neighbourhood_metrics = {
        name: _compact_metrics(frame_metrics(frame)) for name, frame in neighbourhoods.items()
    }

    delay_results: list[dict[str, Any]] = []
    minimum_total_return = math.inf
    worst_max_drawdown = 0.0
    minimum_mean_lower = math.inf
    minimum_sharpe_lower = math.inf
    scenario_index = 0
    for total_delay_bars in (2, 3):
        for cost_bps in ALL_IN_COSTS_BPS:
            delayed = delay_path(candidate, total_delay_bars, cost_bps)
            metrics = frame_metrics(delayed)
            bootstrap = absolute_return_bootstrap(
                delayed["strategy_return"],
                seed=DELAY_SEED_BASE[market] + scenario_index,
            )
            scenario_index += 1
            failed_checks: list[str] = []
            if float(metrics["total_return"]) <= 0.0:
                failed_checks.append("positive_total_return")
            if float(metrics["max_drawdown"]) <= -0.40:
                failed_checks.append("max_drawdown_above_minus_40pct")
            if float(bootstrap["annualized_arithmetic_mean"]["lower"]) <= 0.0:
                failed_checks.append("positive_mean_lower_bound")
            if float(bootstrap["sharpe"]["lower"]) <= 0.0:
                failed_checks.append("positive_sharpe_lower_bound")
            delay_results.append(
                {
                    "scenario": f"delay_{total_delay_bars}_bars_cost_{cost_bps:g}_bps",
                    "metrics": {
                        key: metrics[key]
                        for key in (
                            "total_return",
                            "annualized_arithmetic_mean",
                            "sharpe",
                            "max_drawdown",
                            "annualized_turnover",
                        )
                    },
                    "bootstrap": bootstrap,
                    "passes": not failed_checks,
                    "failed_checks": failed_checks,
                }
            )
            minimum_total_return = min(minimum_total_return, float(metrics["total_return"]))
            worst_max_drawdown = min(worst_max_drawdown, float(metrics["max_drawdown"]))
            minimum_mean_lower = min(
                minimum_mean_lower,
                float(bootstrap["annualized_arithmetic_mean"]["lower"]),
            )
            minimum_sharpe_lower = min(
                minimum_sharpe_lower,
                float(bootstrap["sharpe"]["lower"]),
            )

    selection_frequency = Counter(
        "m={momentum_lookback}|r={reversal_lookback}|trend={trend_weight:.2f}".format(
            **record["selected"]
        )
        for record in fold_records
    )
    records_sha256 = hashlib.sha256(
        json.dumps(fold_records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    result = {
        "metrics_5bps": frame_metrics(candidate),
        "canonical_adaptive": return_metrics(adaptive),
        "volatility_targeted_long": return_metrics(benchmark),
        "bootstrap_vs_volatility_targeted_long": benchmark_bootstrap,
        "bootstrap_vs_canonical_adaptive": adaptive_bootstrap,
        "fold_stability": fold_stability(candidate),
        "calendar_stability": calendar_stability(candidate),
        "cost_scenarios_bps": cost_scenarios,
        "parameter_neighbourhood": neighbourhood_metrics,
        "tail_risk": {
            "expected_shortfall_5pct": expected_shortfall_5pct(candidate["strategy_return"]),
            "benchmark_expected_shortfall_5pct": expected_shortfall_5pct(benchmark),
        },
        "execution_delay_scenarios": {
            "scenarios_tested": len(delay_results),
            "passes": all(record["passes"] for record in delay_results),
            "minimum_total_return": minimum_total_return,
            "worst_max_drawdown": worst_max_drawdown,
            "minimum_annualized_mean_95pct_lower": minimum_mean_lower,
            "minimum_sharpe_95pct_lower": minimum_sharpe_lower,
            "scenario_results": delay_results,
        },
        "fold_selection_summary": {
            "folds": len(fold_records),
            "candidates_tested_per_fold": len(candidate_grid()),
            "shared_selected_candidate_per_fold": 1,
            "selection_frequency": dict(selection_frequency),
            "records_sha256": records_sha256,
        },
        "evaluation": {
            "start": candidate.index[0].isoformat(),
            "end": candidate.index[-1].isoformat(),
            "observations": len(candidate),
            "fold_count": int(candidate["fold"].nunique()),
            "candidate_grid_size": len(candidate_grid()),
        },
    }

    benchmark_passes = (
        float(benchmark_bootstrap["sharpe_delta"]["lower"]) > 0.0
        and float(benchmark_bootstrap["calmar_delta"]["lower"]) > 0.0
    )
    cost_passes = all(
        float(metrics["total_return"]) > 0.0
        and float(metrics["sharpe"]) > 0.0
        and float(metrics["max_drawdown"]) > -0.40
        for metrics in cost_scenarios.values()
    )
    neighbourhood_passes = all(
        float(metrics["total_return"]) > 0.0
        and float(metrics["sharpe"]) > 0.0
        and float(metrics["max_drawdown"]) > -0.40
        for metrics in neighbourhood_metrics.values()
    )
    tail_passes = float(result["tail_risk"]["expected_shortfall_5pct"]) > float(
        result["tail_risk"]["benchmark_expected_shortfall_5pct"]
    )
    result["gates"] = {
        "development_benchmark_relative_risk_adjusted": ("pass" if benchmark_passes else "fail"),
        "fold_stability": "pass" if result["fold_stability"]["passes"] else "fail",
        "year_stability": "pass" if result["calendar_stability"]["passes"] else "fail",
        "turnover_and_5_7.5_10_15bps_viability": "pass" if cost_passes else "fail",
        "parameter_neighbourhood_stability": ("pass" if neighbourhood_passes else "fail"),
        "tail_risk": "pass" if tail_passes else "fail",
        "execution_delay_robustness": (
            "pass" if result["execution_delay_scenarios"]["passes"] else "fail"
        ),
        "separate_spread_slippage_impact_latency": "blocked",
        "capacity": "blocked",
        "untouched_market_validation": "blocked",
        "prospective_forward_validation": "blocked",
    }
    return result


def analyze(artifact_dir: Path) -> dict[str, Any]:
    prices = {
        market: load_snapshot(
            artifact_dir / market / "snapshot" / f"okx-{market}-1Dutc.csv",
            market,
        )
        for market in MARKETS
    }
    canonical = {
        market: load_canonical_returns(
            artifact_dir / market / "walk_forward_returns.csv",
            market,
        )
        for market in MARKETS
    }
    candidate_paths, fold_records = build_shared_path(prices, rule="maximin")
    mean_paths, _ = build_shared_path(prices, rule="mean_score")
    rank_paths, _ = build_shared_path(prices, rule="rank_sum")

    markets = {
        market: analyze_market(
            market,
            candidate_paths[market],
            canonical[market],
            {
                "mean_score": mean_paths[market],
                "rank_sum": rank_paths[market],
            },
            fold_records,
        )
        for market in MARKETS
    }
    joint_gates: dict[str, str] = {}
    for gate in markets[MARKETS[0]]["gates"]:
        statuses = [markets[market]["gates"][gate] for market in MARKETS]
        if "fail" in statuses:
            joint_gates[gate] = "fail"
        elif "blocked" in statuses:
            joint_gates[gate] = "blocked"
        else:
            joint_gates[gate] = "pass"

    required_freeze_gates = (
        "development_benchmark_relative_risk_adjusted",
        "fold_stability",
        "year_stability",
        "turnover_and_5_7.5_10_15bps_viability",
        "parameter_neighbourhood_stability",
        "tail_risk",
        "execution_delay_robustness",
    )
    freeze_eligible = all(joint_gates[gate] == "pass" for gate in required_freeze_gates)
    return {
        "hypothesis": (
            "A fold-local cross-market maximin selector chooses one shared parameter tuple "
            "that generalizes across BTC-USDT and ETH-USDT and passes every development-stage "
            "architecture-freeze gate."
        ),
        "economic_rationale": (
            "Market-specific winner-take-all selection can overfit idiosyncratic regimes. "
            "Maximizing the weaker of the two prior-window canonical scores forces one "
            "parameter set to earn acceptable evidence in both development markets before "
            "deployment."
        ),
        "canonical_signature": CANONICAL_SIGNATURE,
        "candidate_accounting": {
            "architecture_candidates_searched": 1,
            "passed": 1 if freeze_eligible else 0,
            "rejected": 0 if freeze_eligible else 1,
            "declared_grid_members_scored_per_fold": len(candidate_grid()),
            "shared_candidates_selected_per_fold": 1,
            "neighbourhood_stresses": ["mean_score", "rank_sum"],
            "cost_stresses_bps": list(ALL_IN_COSTS_BPS),
            "delay_stresses_total_bars": [2, 3],
        },
        "source": {
            **SOURCE,
            "evaluation_start": EXPECTED_EVALUATION_START.isoformat(),
            "evaluation_end": EXPECTED_EVALUATION_END.isoformat(),
            "observations_per_market": EXPECTED_OBSERVATIONS,
            "expected_hashes": EXPECTED_HASHES,
        },
        "markets": markets,
        "joint_gates": joint_gates,
        "architecture_freeze_eligible": freeze_eligible,
        "live_eligible": False,
        "verdict": "supported" if freeze_eligible else "rejected",
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets and may be used only for architecture design.",
            "SOL-USDT was not read or used and remains a consumed sealed holdout unavailable for tuning.",
            "Mean-score and rank-sum rules are predeclared neighbourhood stresses, not separately selected architectures.",
            "Moving-block resampling creates artificial joins and preserves dependence only within 20-session blocks.",
            "Delay scenarios shift daily positions and do not model executable next-open fills.",
            "The 7.5, 10 and 15 bps cases are aggregate repricings, not measured spread, slippage, impact or latency.",
            "Capacity and prospective forward evidence remain unavailable.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
