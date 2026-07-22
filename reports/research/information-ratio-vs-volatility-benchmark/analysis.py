from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
STRATEGY_RETURN_COLUMN = "strategy_return"
BENCHMARK_RETURN_COLUMN = "benchmark_volatility_targeted_long_return"
ANNUALIZATION = 365
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072315, "ETH-USDT": 2026072316}
CANONICAL_SIGNATURE = (
    "information-ratio-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long|"
    "active-return=strategy-return-minus-benchmark-return|"
    "metric=annualized-information-ratio-mean-active-return-over-sample-tracking-error|"
    "annualization=365|claim=information-ratio>0-in-both-markets|"
    "resampling=paired-noncircular-moving-block-bootstrap|block-length=20-sessions|"
    "resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072315,ETH-USDT:2026072316|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_timestamps(values: pd.Series) -> pd.DatetimeIndex:
    raw = values.astype("string")
    explicit_zone = raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if not bool(explicit_zone.all()):
        raise ValueError("timestamps must include an explicit timezone offset")

    timestamps = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = timestamps[1:] - timestamps[:-1]
        if not bool((intervals == pd.Timedelta(days=1)).all()):
            raise ValueError("timestamps must have exact daily cadence")
    return timestamps


def load_returns(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", STRATEGY_RETURN_COLUMN, BENCHMARK_RETURN_COLUMN}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")

    validated = pd.DataFrame({"timestamp": _validated_timestamps(frame["timestamp"])})
    for column in (STRATEGY_RETURN_COLUMN, BENCHMARK_RETURN_COLUMN):
        values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(values <= -1.0):
            raise ValueError(f"{column} must contain finite returns greater than -100%")
        validated[column] = values
    return validated


def information_ratio(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    annualization: int = ANNUALIZATION,
) -> float:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if strategy.shape != benchmark.shape:
        raise ValueError("strategy and benchmark returns must have identical shapes")
    if strategy.ndim != 1 or strategy.size < 2:
        raise ValueError("return inputs must be one-dimensional with at least two values")
    if not np.isfinite(strategy).all() or not np.isfinite(benchmark).all():
        raise ValueError("return inputs must be finite")
    if isinstance(annualization, bool) or not isinstance(annualization, int):
        raise ValueError("annualization must be an integer")
    if annualization < 2:
        raise ValueError("annualization must be at least 2")

    active_returns = strategy - benchmark
    tracking_error = float(np.std(active_returns, ddof=1))
    if tracking_error <= 0.0:
        raise ValueError("active returns must have positive sample tracking error")
    return float(np.sqrt(annualization) * np.mean(active_returns) / tracking_error)


def moving_block_indices(
    observation_count: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if observation_count < 2:
        raise ValueError("observation_count must be at least 2")
    if isinstance(block_length, bool) or not isinstance(block_length, int):
        raise ValueError("block_length must be an integer")
    if block_length < 1 or block_length > observation_count:
        raise ValueError("block_length must be between 1 and observation_count")

    block_count = math.ceil(observation_count / block_length)
    starts = rng.integers(0, observation_count - block_length + 1, size=block_count)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observation_count]


def bootstrap_information_ratio(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float]:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    observed = information_ratio(strategy, benchmark)
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("confidence must be a real number")
    if not math.isfinite(float(confidence)) or not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be finite and strictly between zero and one")

    rng = np.random.default_rng(seed)
    estimates = np.empty(resamples, dtype=float)
    for index in range(resamples):
        sample_indices = moving_block_indices(strategy.size, block_length, rng)
        estimates[index] = information_ratio(strategy[sample_indices], benchmark[sample_indices])

    alpha = 1.0 - float(confidence)
    lower, upper = np.quantile(estimates, [alpha / 2.0, 1.0 - alpha / 2.0])
    active_returns = strategy - benchmark
    return {
        "annualized_active_return": float(np.mean(active_returns) * ANNUALIZATION),
        "annualized_tracking_error": float(np.std(active_returns, ddof=1) * np.sqrt(ANNUALIZATION)),
        "information_ratio": observed,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "probability_information_ratio_positive": float(np.mean(estimates > 0.0)),
    }


def analyze_market(artifact_dir: str | Path, market: str) -> dict[str, object]:
    returns_path = Path(artifact_dir) / market / "walk_forward_returns.csv"
    returns = load_returns(returns_path)
    result = bootstrap_information_ratio(
        returns[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float),
        returns[BENCHMARK_RETURN_COLUMN].to_numpy(dtype=float),
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        confidence=CONFIDENCE,
        seed=SEEDS[market],
    )
    result["observations"] = len(returns)
    result["period_start"] = returns["timestamp"].iloc[0].isoformat()
    result["period_end"] = returns["timestamp"].iloc[-1].isoformat()
    result["return_file_sha256"] = file_sha256(returns_path)
    result["passed"] = bool(result["ci_lower"] > 0.0)
    return result


def build_result(artifact_dir: str | Path) -> dict[str, object]:
    markets = {market: analyze_market(artifact_dir, market) for market in MARKETS}
    joint_passed = all(bool(markets[market]["passed"]) for market in MARKETS)
    failed_markets = [market for market in MARKETS if not bool(markets[market]["passed"])]
    rejection_reason = None
    if failed_markets:
        rejection_reason = (
            "The 95% paired moving-block-bootstrap lower bound for the annualized "
            "information ratio was non-positive in: " + ", ".join(failed_markets)
        )

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "The adaptive strategy has a positive annualized information ratio versus "
            "volatility-targeted long in both BTC-USDT and ETH-USDT."
        ),
        "candidate_accounting": {
            "searched": 1,
            "passed": int(joint_passed),
            "rejected": int(not joint_passed),
        },
        "settings": {
            "benchmark": "volatility-targeted-long",
            "annualization": ANNUALIZATION,
            "block_length_sessions": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "information_ratio_definition": (
                "sqrt(365) * mean(strategy_return - benchmark_return) / "
                "sample_std(strategy_return - benchmark_return)"
            ),
            "seeds": SEEDS,
        },
        "markets": markets,
        "verdict": "supported" if joint_passed else "rejected",
        "rejection_reason": rejection_reason,
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29957899078,
            "source_artifact_id": 8544795485,
            "source_artifact_name": "quant-research-source-1374-attempt-1",
            "source_artifact_sha256": (
                "a4177288bba8a1599576688d8481546149512e96ad149c7b91f2e6f00d71fd31"
            ),
            "source_head_sha": "160fb816405deebbd142289f5fbefb8e5d403646",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_result(args.artifact_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
