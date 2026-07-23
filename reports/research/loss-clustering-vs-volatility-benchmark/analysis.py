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
EXPECTED_RETURN_FILE_SHA256 = {
    "BTC-USDT": "ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce",
    "ETH-USDT": "bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047",
}
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072325, "ETH-USDT": 2026072326}
CANONICAL_SIGNATURE = (
    "loss-clustering-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long|"
    "loss=return<0|metric=P(current-loss|previous-loss)|"
    "delta=benchmark-loss-clustering-minus-strategy-loss-clustering|"
    "claim=delta>0-in-both-markets|"
    "resampling=paired-noncircular-moving-block-bootstrap-excluding-sampled-block-joins|"
    "block-length=20-sessions|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072325,ETH-USDT:2026072326|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_return_file_sha256(path: str | Path, market: str) -> str:
    try:
        expected = EXPECTED_RETURN_FILE_SHA256[market]
    except KeyError as exc:
        raise ValueError(f"unsupported market: {market}") from exc
    observed = file_sha256(path)
    if observed != expected:
        raise ValueError(
            f"{market} return file SHA-256 mismatch: expected {expected}, observed {observed}"
        )
    return observed


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
    if len(validated) < 2:
        raise ValueError("at least two aligned return observations are required")
    return validated


def loss_transition_counts(returns: np.ndarray) -> tuple[int, int]:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or values.size < 2:
        raise ValueError("returns must be a one-dimensional array with at least two observations")
    if not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("returns must be finite and greater than -100%")
    previous_loss = values[:-1] < 0.0
    loss_after_loss = previous_loss & (values[1:] < 0.0)
    return int(loss_after_loss.sum()), int(previous_loss.sum())


def loss_clustering_probability(returns: np.ndarray) -> float:
    consecutive_losses, previous_losses = loss_transition_counts(returns)
    if previous_losses == 0:
        raise ValueError("loss clustering requires at least one prior loss observation")
    return consecutive_losses / previous_losses


def sampled_block_indices(
    observation_count: int,
    block_length: int,
    rng: np.random.Generator,
) -> list[np.ndarray]:
    if observation_count < 2:
        raise ValueError("observation_count must be at least two")
    if isinstance(block_length, bool) or not isinstance(block_length, int):
        raise ValueError("block_length must be an integer")
    if block_length < 2 or block_length > observation_count:
        raise ValueError("block_length must be between two and observation_count")
    block_count = math.ceil(observation_count / block_length)
    remaining = observation_count
    blocks: list[np.ndarray] = []
    for _ in range(block_count):
        length = min(block_length, remaining)
        start = int(rng.integers(0, observation_count - length + 1))
        blocks.append(np.arange(start, start + length, dtype=int))
        remaining -= length
    return blocks


def _block_transition_counts(returns: np.ndarray, blocks: list[np.ndarray]) -> tuple[int, int]:
    consecutive = 0
    previous = 0
    for block in blocks:
        block_consecutive, block_previous = loss_transition_counts(returns[block])
        consecutive += block_consecutive
        previous += block_previous
    return consecutive, previous


def bootstrap_loss_clustering_delta(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float | int]:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if strategy.ndim != 1 or benchmark.ndim != 1 or strategy.size != benchmark.size:
        raise ValueError("strategy and benchmark returns must be aligned one-dimensional arrays")
    if strategy.size < 2:
        raise ValueError("at least two aligned returns are required")
    if not np.isfinite(strategy).all() or not np.isfinite(benchmark).all():
        raise ValueError("returns must be finite")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("confidence must be a real number")
    if not math.isfinite(float(confidence)) or not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be finite and strictly between zero and one")

    strategy_probability = loss_clustering_probability(strategy)
    benchmark_probability = loss_clustering_probability(benchmark)
    observed_delta = benchmark_probability - strategy_probability

    rng = np.random.default_rng(seed)
    sampled_deltas = np.empty(resamples, dtype=float)
    for index in range(resamples):
        blocks = sampled_block_indices(strategy.size, block_length, rng)
        strategy_consecutive, strategy_previous = _block_transition_counts(strategy, blocks)
        benchmark_consecutive, benchmark_previous = _block_transition_counts(benchmark, blocks)
        if strategy_previous == 0 or benchmark_previous == 0:
            raise ValueError("sampled blocks must contain prior losses for both return series")
        sampled_deltas[index] = (
            benchmark_consecutive / benchmark_previous
            - strategy_consecutive / strategy_previous
        )

    alpha = 1.0 - float(confidence)
    lower, upper = np.quantile(sampled_deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    strategy_consecutive, strategy_previous = loss_transition_counts(strategy)
    benchmark_consecutive, benchmark_previous = loss_transition_counts(benchmark)
    return {
        "strategy_loss_clustering_probability": strategy_probability,
        "benchmark_loss_clustering_probability": benchmark_probability,
        "observed_delta": observed_delta,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "probability_delta_positive": float(np.mean(sampled_deltas > 0.0)),
        "strategy_loss_after_loss_count": strategy_consecutive,
        "strategy_prior_loss_count": strategy_previous,
        "benchmark_loss_after_loss_count": benchmark_consecutive,
        "benchmark_prior_loss_count": benchmark_previous,
    }


def analyze_market(artifact_dir: str | Path, market: str) -> dict[str, object]:
    returns_path = Path(artifact_dir) / market / "walk_forward_returns.csv"
    return_file_sha256 = verify_return_file_sha256(returns_path, market)
    returns = load_returns(returns_path)
    result = bootstrap_loss_clustering_delta(
        returns[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float),
        returns[BENCHMARK_RETURN_COLUMN].to_numpy(dtype=float),
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        confidence=CONFIDENCE,
        seed=SEEDS[market],
    )
    return {
        **result,
        "observations": int(len(returns)),
        "period_start": returns["timestamp"].iloc[0].isoformat(),
        "period_end": returns["timestamp"].iloc[-1].isoformat(),
        "return_file_sha256": return_file_sha256,
        "passed": bool(result["ci_lower"] > 0.0),
    }


def build_result(artifact_dir: str | Path) -> dict[str, object]:
    markets = {market: analyze_market(artifact_dir, market) for market in MARKETS}
    joint_passed = all(bool(markets[market]["passed"]) for market in MARKETS)
    failed_markets = [market for market in MARKETS if not bool(markets[market]["passed"])]
    rejection_reason = None
    if failed_markets:
        rejection_reason = (
            "The 95% paired moving-block-bootstrap lower bound for benchmark-minus-strategy "
            "loss-clustering probability was non-positive in: " + ", ".join(failed_markets)
        )
    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "The adaptive strategy has a lower probability of a loss immediately following "
            "a loss than volatility-targeted long in both BTC-USDT and ETH-USDT."
        ),
        "candidate_accounting": {
            "searched": 1,
            "passed": int(joint_passed),
            "rejected": int(not joint_passed),
        },
        "settings": {
            "benchmark": "volatility-targeted long",
            "loss_definition": "net return strictly below zero",
            "metric": "P(current loss | previous loss)",
            "delta": "benchmark probability minus strategy probability",
            "block_length_sessions": BLOCK_LENGTH,
            "sampled_block_join_policy": "exclude transitions across sampled block joins",
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "seeds": SEEDS,
        },
        "markets": markets,
        "verdict": "supported" if joint_passed else "rejected",
        "rejection_reason": rejection_reason,
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29987295837,
            "source_artifact_id": 8555542657,
            "source_artifact_name": "quant-research-source-1737-attempt-1",
            "source_artifact_sha256": (
                "4dbb277373d818c84487f021a2c02f268e95714c8aaf6c70672f3cd068f3c7c3"
            ),
            "source_code_commit": "f25d1cb2a8068dc49c0e5e6c83c522a445f3ef28",
            "current_main_commit": "d1ecd2c00ad0d1f4347af1f49f97569a36cc6331",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare consecutive-loss clustering in the adaptive strategy and "
            "volatility-targeted-long benchmark."
        )
    )
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
