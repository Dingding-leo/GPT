from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
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
TRANSACTION_COST_BPS = 10.0
ANNUALIZATION = 365
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072323, "ETH-USDT": 2026072324}
SOURCE_WORKFLOW_RUN_ID = 30003533823
SOURCE_ARTIFACT_ID = 8562021482
SOURCE_ARTIFACT_NAME = "quant-research-source-1927-attempt-1"
SOURCE_ARTIFACT_SHA256 = "852ef5a2a643d3d8332410ce9f34a9a5b32a8ca69fb42b8058546719c25068e4"
SOURCE_HEAD_SHA = "abb0e4a1837c403026219273a65cc9ec7645d273"
EXPECTED_EVALUATION_START = pd.Timestamp("2020-01-11T00:00:00Z")
EXPECTED_EVALUATION_END = pd.Timestamp("2026-07-22T00:00:00Z")
EXPECTED_OBSERVATIONS = 2_385
EXPECTED_HASHES = {
    "BTC-USDT": {
        "snapshot": "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1",
        "returns": "ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce",
    },
    "ETH-USDT": {
        "snapshot": "842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f",
        "returns": "bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047",
    },
}
CANONICAL_SIGNATURE = (
    "equal-weight-candidate-ensemble-vs-adaptive-v1|"
    "markets=BTC-USDT,ETH-USDT|source=immutable-OKX-snapshots-and-persisted-net-"
    "rolling-oos-returns|ensemble=equal-weight-mean-of-all-27-declared-candidate-"
    "positions|grid=momentum30,90,180-reversal2,5,10-trend0.55,0.70,0.85|"
    "execution=one-bar-delay-long-cash-10bps-continuous-position-cash-entry-at-"
    "evaluation-start|comparison=ensemble-minus-adaptive-winner-take-all|"
    "metrics=annualized-arithmetic-mean-delta,annualized-sharpe-delta|"
    "turnover=adaptive-minus-ensemble-annualized-absolute-position-turnover|"
    "resampling=paired-noncircular-moving-block-bootstrap|block-length=20-sessions|"
    "resamples=2000|confidence=0.95|seeds=BTC-USDT:2026072323,ETH-USDT:2026072324|"
    "pass=mean-and-sharpe-lower-bounds-positive-in-both-markets|candidate_count=1"
)
_TIMEZONE_PATTERN = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def candidate_grid() -> list[dict[str, float | int]]:
    return [
        {
            "momentum_lookback": momentum,
            "reversal_lookback": reversal,
            "trend_weight": trend_weight,
            "reversal_weight": round(1.0 - trend_weight, 10),
        }
        for momentum, reversal, trend_weight in itertools.product(
            MOMENTUM_LOOKBACKS,
            REVERSAL_LOOKBACKS,
            TREND_WEIGHTS,
        )
    ]


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


def load_adaptive_returns(
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
    required = {"timestamp", "strategy_return", "turnover"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")
    timestamps = _validated_timestamps(frame["timestamp"])
    validated = pd.DataFrame({"timestamp": timestamps})
    for column in ("strategy_return", "turnover"):
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.isna().any() or not np.isfinite(numeric.to_numpy(dtype=float)).all():
            raise ValueError(f"{column} must contain only finite values")
        validated[column] = numeric.to_numpy(dtype=float)
    if (validated["strategy_return"] <= -1.0).any():
        raise ValueError("strategy returns must remain greater than -100%")
    if (validated["turnover"] < 0.0).any():
        raise ValueError("turnover must be non-negative")
    if len(validated) != EXPECTED_OBSERVATIONS:
        raise ValueError(f"expected {EXPECTED_OBSERVATIONS} OOS observations")
    if validated["timestamp"].iloc[0] != EXPECTED_EVALUATION_START:
        raise ValueError("unexpected evaluation start")
    if validated["timestamp"].iloc[-1] != EXPECTED_EVALUATION_END:
        raise ValueError("unexpected evaluation end")
    return validated


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
    trend_score = (
        trend_mean / trend_std.replace(0.0, np.nan) * math.sqrt(momentum_lookback)
    )

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

    reversal_weight = 1.0 - trend_weight
    ensemble_score = (
        trend_weight * trend_score + reversal_weight * reversal_score
    ).clip(-4.0, 4.0)
    directional_signal = pd.Series(
        np.tanh(ensemble_score.to_numpy(dtype=float)),
        index=ensemble_score.index,
    )
    realized_volatility = risk_scale * math.sqrt(ANNUALIZATION)
    volatility_scalar = (
        TARGET_VOLATILITY / realized_volatility.replace(0.0, np.nan)
    ).clip(lower=0.0, upper=MAX_POSITION)
    target = (directional_signal * volatility_scalar).clip(MIN_POSITION, MAX_POSITION)
    return target.replace([np.inf, -np.inf], np.nan).fillna(0.0)


def equal_weight_candidate_position(prices: pd.Series) -> pd.Series:
    positions = []
    for candidate in candidate_grid():
        target = build_target_position(
            prices,
            momentum_lookback=int(candidate["momentum_lookback"]),
            reversal_lookback=int(candidate["reversal_lookback"]),
            trend_weight=float(candidate["trend_weight"]),
        )
        positions.append(target.shift(1).fillna(0.0))
    return pd.concat(positions, axis=1).mean(axis=1).rename("ensemble_position")


def build_ensemble_frame(
    prices: pd.Series,
    evaluation_timestamps: pd.DatetimeIndex,
) -> pd.DataFrame:
    if not evaluation_timestamps.is_monotonic_increasing or evaluation_timestamps.has_duplicates:
        raise ValueError("evaluation timestamps must be unique and increasing")
    position = equal_weight_candidate_position(prices).reindex(evaluation_timestamps)
    asset_return = prices.pct_change().fillna(0.0).reindex(evaluation_timestamps)
    if position.isna().any() or asset_return.isna().any():
        raise ValueError("evaluation timestamps must be contained in the snapshot")

    turnover = position.diff().abs()
    turnover.iloc[0] = abs(float(position.iloc[0]))
    trading_cost = turnover * TRANSACTION_COST_BPS / 10_000.0
    strategy_return = position * asset_return - trading_cost
    if not np.isfinite(strategy_return.to_numpy(dtype=float)).all():
        raise ValueError("ensemble returns must be finite")
    if (strategy_return <= -1.0).any():
        raise ValueError("ensemble returns must remain greater than -100%")
    return pd.DataFrame(
        {
            "asset_return": asset_return,
            "position": position,
            "turnover": turnover,
            "trading_cost": trading_cost,
            "strategy_return": strategy_return,
        },
        index=evaluation_timestamps,
    )


def annualized_arithmetic_mean(returns: np.ndarray) -> float:
    return float(np.mean(returns)) * ANNUALIZATION


def annualized_sharpe(returns: np.ndarray) -> float:
    standard_deviation = float(np.std(returns, ddof=0))
    if standard_deviation == 0.0:
        return 0.0
    return float(np.mean(returns)) / standard_deviation * math.sqrt(ANNUALIZATION)


def total_return(returns: np.ndarray) -> float:
    return float(np.prod(1.0 + returns) - 1.0)


def noncircular_block_indices(
    observations: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if block_length <= 0 or block_length > observations:
        raise ValueError("block length must be in [1, observations]")
    blocks_needed = math.ceil(observations / block_length)
    starts = rng.integers(0, observations - block_length + 1, size=blocks_needed)
    blocks = [np.arange(start, start + block_length) for start in starts]
    return np.concatenate(blocks)[:observations]


def interval(values: np.ndarray) -> dict[str, float]:
    alpha = (1.0 - CONFIDENCE) / 2.0
    lower, upper = np.quantile(values, [alpha, 1.0 - alpha])
    return {"lower": float(lower), "upper": float(upper)}


def analyze_market(artifact_dir: Path, market: str) -> dict[str, Any]:
    snapshot_path = artifact_dir / market / "snapshot" / f"okx-{market}-1Dutc.csv"
    returns_path = artifact_dir / market / "walk_forward_returns.csv"
    prices = load_snapshot(snapshot_path, market)
    adaptive = load_adaptive_returns(returns_path, market)
    evaluation_index = pd.DatetimeIndex(adaptive["timestamp"])
    ensemble = build_ensemble_frame(prices, evaluation_index)

    ensemble_returns = ensemble["strategy_return"].to_numpy(dtype=float)
    adaptive_returns = adaptive["strategy_return"].to_numpy(dtype=float)
    ensemble_turnover = ensemble["turnover"].to_numpy(dtype=float)
    adaptive_turnover = adaptive["turnover"].to_numpy(dtype=float)

    observed = {
        "ensemble_annualized_arithmetic_mean": annualized_arithmetic_mean(ensemble_returns),
        "adaptive_annualized_arithmetic_mean": annualized_arithmetic_mean(adaptive_returns),
        "annualized_arithmetic_mean_delta": (
            annualized_arithmetic_mean(ensemble_returns)
            - annualized_arithmetic_mean(adaptive_returns)
        ),
        "ensemble_annualized_sharpe": annualized_sharpe(ensemble_returns),
        "adaptive_annualized_sharpe": annualized_sharpe(adaptive_returns),
        "annualized_sharpe_delta": (
            annualized_sharpe(ensemble_returns) - annualized_sharpe(adaptive_returns)
        ),
        "ensemble_total_return": total_return(ensemble_returns),
        "adaptive_total_return": total_return(adaptive_returns),
        "ensemble_annualized_turnover": float(np.mean(ensemble_turnover)) * ANNUALIZATION,
        "adaptive_annualized_turnover": float(np.mean(adaptive_turnover)) * ANNUALIZATION,
        "annualized_turnover_reduction": (
            float(np.mean(adaptive_turnover - ensemble_turnover)) * ANNUALIZATION
        ),
    }

    rng = np.random.default_rng(SEEDS[market])
    mean_deltas = np.empty(RESAMPLES)
    sharpe_deltas = np.empty(RESAMPLES)
    turnover_reductions = np.empty(RESAMPLES)
    for resample in range(RESAMPLES):
        sampled = noncircular_block_indices(len(adaptive), BLOCK_LENGTH, rng)
        sampled_ensemble = ensemble_returns[sampled]
        sampled_adaptive = adaptive_returns[sampled]
        mean_deltas[resample] = annualized_arithmetic_mean(
            sampled_ensemble
        ) - annualized_arithmetic_mean(sampled_adaptive)
        sharpe_deltas[resample] = annualized_sharpe(sampled_ensemble) - annualized_sharpe(
            sampled_adaptive
        )
        turnover_reductions[resample] = (
            float(np.mean(adaptive_turnover[sampled] - ensemble_turnover[sampled]))
            * ANNUALIZATION
        )

    mean_interval = interval(mean_deltas)
    sharpe_interval = interval(sharpe_deltas)
    turnover_interval = interval(turnover_reductions)
    passes = mean_interval["lower"] > 0.0 and sharpe_interval["lower"] > 0.0
    failure_reasons = []
    if mean_interval["lower"] <= 0.0:
        failure_reasons.append("annualized arithmetic mean delta lower bound is non-positive")
    if sharpe_interval["lower"] <= 0.0:
        failure_reasons.append("annualized Sharpe delta lower bound is non-positive")

    return {
        "observations": len(adaptive),
        "evaluation_start": evaluation_index[0].isoformat(),
        "evaluation_end": evaluation_index[-1].isoformat(),
        "constituent_candidates": len(candidate_grid()),
        **observed,
        "annualized_arithmetic_mean_delta_interval": mean_interval,
        "annualized_arithmetic_mean_delta_probability_positive": float(
            np.mean(mean_deltas > 0.0)
        ),
        "annualized_sharpe_delta_interval": sharpe_interval,
        "annualized_sharpe_delta_probability_positive": float(
            np.mean(sharpe_deltas > 0.0)
        ),
        "annualized_turnover_reduction_interval": turnover_interval,
        "annualized_turnover_reduction_probability_positive": float(
            np.mean(turnover_reductions > 0.0)
        ),
        "passes": passes,
        "failure_reasons": failure_reasons,
        "source_hashes": EXPECTED_HASHES[market],
    }


def build_result(artifact_dir: Path) -> dict[str, Any]:
    markets = {market: analyze_market(artifact_dir, market) for market in MARKETS}
    passes = all(result["passes"] for result in markets.values())
    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "An equal-weight ensemble of all 27 declared candidate positions improves both "
            "annualized arithmetic mean net return and annualized Sharpe over the persisted "
            "adaptive winner-take-all path in BTC-USDT and ETH-USDT."
        ),
        "economic_rationale": (
            "Averaging the fixed candidate grid should diversify parameter-selection error and "
            "reduce unnecessary position changes if winner-take-all selection is unstable."
        ),
        "source": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "workflow_run_id": SOURCE_WORKFLOW_RUN_ID,
            "artifact_id": SOURCE_ARTIFACT_ID,
            "artifact_name": SOURCE_ARTIFACT_NAME,
            "artifact_sha256": SOURCE_ARTIFACT_SHA256,
            "source_head_sha": SOURCE_HEAD_SHA,
        },
        "method": {
            "strategy_candidates_searched": 1,
            "ensemble_constituents": candidate_grid(),
            "constituent_count": len(candidate_grid()),
            "weighting": "equal weight across all constituent positions on every session",
            "execution": (
                "one-bar delayed long/cash positions; 10 bps per unit turnover; continuous "
                "position after cash entry at evaluation start"
            ),
            "comparison": "equal-weight ensemble minus persisted adaptive winner-take-all path",
            "primary_metrics": [
                "annualized arithmetic mean delta",
                "annualized Sharpe delta",
            ],
            "diagnostic_metric": "adaptive minus ensemble annualized turnover",
            "bootstrap": {
                "kind": "paired non-circular moving-block bootstrap over observed daily rows",
                "block_length": BLOCK_LENGTH,
                "resamples": RESAMPLES,
                "confidence": CONFIDENCE,
                "seeds": SEEDS,
            },
            "pass_rule": (
                "both primary metric 95% lower bounds must be positive in both markets"
            ),
        },
        "candidate_accounting": {
            "searched": 1,
            "passed": int(passes),
            "rejected": int(not passes),
        },
        "markets": markets,
        "verdict": "supported" if passes else "rejected",
        "claim_scope": (
            "Development-market comparison only; no sealed-holdout, alpha, or deployment claim."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
