from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
STRATEGY_COLUMN = "strategy_return"
BENCHMARK_COLUMN = "benchmark_volatility_targeted_long_return"
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072309, "ETH-USDT": 2026072310}
CANONICAL_SIGNATURE = (
    "ulcer-index-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long|"
    "metric=ulcer-index|nav-start=1|drawdown=nav/running-peak-minus-1|"
    "ulcer-index=sqrt(mean(drawdown-squared))|"
    "claim=benchmark-minus-strategy-ulcer-index>0-in-both-markets|"
    "resampling=paired-noncircular-moving-block-bootstrap|block-length=20-sessions|"
    "resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072309,ETH-USDT:2026072310|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_returns(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", STRATEGY_COLUMN, BENCHMARK_COLUMN}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")

    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("returns timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = timestamps[1:] - timestamps[:-1]
        if not bool((intervals == pd.Timedelta(days=1)).all()):
            raise ValueError("returns timestamps must have exact daily cadence")

    validated = pd.DataFrame({"timestamp": timestamps})
    for column in (STRATEGY_COLUMN, BENCHMARK_COLUMN):
        values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(values <= -1.0):
            raise ValueError(f"{column} must contain finite returns greater than -100%")
        validated[column] = values
    return validated


def ulcer_index(returns: np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or values.size < 2 or not np.isfinite(values).all():
        raise ValueError("returns must be a one-dimensional finite array with at least two values")
    if np.any(values <= -1.0):
        raise ValueError("returns must be greater than -100%")

    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    peaks = np.maximum.accumulate(nav)
    drawdowns = nav / peaks - 1.0
    return float(np.sqrt(np.mean(np.square(drawdowns))))


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


def bootstrap_ulcer_reduction(
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
    if strategy.shape != benchmark.shape:
        raise ValueError("strategy and benchmark returns must have identical shapes")
    if strategy.ndim != 1 or strategy.size < 2:
        raise ValueError("paired returns must be one-dimensional with at least two observations")
    if not np.isfinite(strategy).all() or not np.isfinite(benchmark).all():
        raise ValueError("paired returns must be finite")
    if np.any(strategy <= -1.0) or np.any(benchmark <= -1.0):
        raise ValueError("paired returns must be greater than -100%")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("confidence must be a real number")
    if not math.isfinite(float(confidence)) or not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be finite and strictly between zero and one")

    strategy_ulcer = ulcer_index(strategy)
    benchmark_ulcer = ulcer_index(benchmark)
    observed_reduction = benchmark_ulcer - strategy_ulcer

    rng = np.random.default_rng(seed)
    reductions = np.empty(resamples, dtype=float)
    for index in range(resamples):
        sample_indices = moving_block_indices(strategy.size, block_length, rng)
        reductions[index] = ulcer_index(benchmark[sample_indices]) - ulcer_index(
            strategy[sample_indices]
        )

    alpha = 1.0 - float(confidence)
    lower, upper = np.quantile(reductions, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "strategy_ulcer_index": strategy_ulcer,
        "benchmark_ulcer_index": benchmark_ulcer,
        "observed_reduction": observed_reduction,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "probability_reduction_positive": float(np.mean(reductions > 0.0)),
    }


def analyze_market(path: str | Path, market: str) -> dict[str, object]:
    frame = load_returns(path)
    result = bootstrap_ulcer_reduction(
        frame[STRATEGY_COLUMN].to_numpy(dtype=float),
        frame[BENCHMARK_COLUMN].to_numpy(dtype=float),
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        confidence=CONFIDENCE,
        seed=SEEDS[market],
    )
    result["observations"] = len(frame)
    result["period_start"] = frame["timestamp"].iloc[0].isoformat()
    result["period_end"] = frame["timestamp"].iloc[-1].isoformat()
    result["return_file_sha256"] = file_sha256(path)
    result["passed"] = bool(result["ci_lower"] > 0.0)
    return result


def build_result(artifact_dir: str | Path) -> dict[str, object]:
    root = Path(artifact_dir)
    markets = {
        market: analyze_market(root / market / "walk_forward_returns.csv", market)
        for market in MARKETS
    }
    joint_passed = all(bool(markets[market]["passed"]) for market in MARKETS)
    failed_markets = [market for market in MARKETS if not bool(markets[market]["passed"])]
    rejection_reason = None
    if failed_markets:
        rejection_reason = (
            "The 95% paired moving-block-bootstrap lower bound for the benchmark-minus-"
            "strategy Ulcer Index reduction was non-positive in: " + ", ".join(failed_markets)
        )

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "The strategy has a lower Ulcer Index than the volatility-targeted-long benchmark "
            "in both BTC-USDT and ETH-USDT."
        ),
        "candidate_accounting": {
            "searched": 1,
            "passed": int(joint_passed),
            "rejected": int(not joint_passed),
        },
        "settings": {
            "block_length_sessions": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "benchmark": "volatility-targeted-long",
            "ulcer_index_definition": (
                "sqrt(mean((nav / running_peak - 1)^2)), with nav starting at 1"
            ),
            "reduction_definition": "benchmark_ulcer_index - strategy_ulcer_index",
            "seeds": SEEDS,
        },
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run": 29952479109,
            "source_artifact_id": 8542699045,
            "source_artifact_name": "quant-research-source-1321-attempt-1",
            "source_artifact_sha256": (
                "edf630f5372209f12ccc770751872f82523624ccafdfd7c849bae1971ab4aefc"
            ),
            "source_head_sha": "0945532759010d0d94638c69ea0e5a175c4ae964",
            "development_markets": list(MARKETS),
        },
        "markets": markets,
        "verdict": "passed" if joint_passed else "rejected",
        "rejection_reason": rejection_reason,
        "claim_scope": (
            "Development-market diagnostic only; no deployable strategy improvement is claimed."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_result(args.artifact_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
