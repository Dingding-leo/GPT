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
TAIL_FRACTION = 0.05
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072319, "ETH-USDT": 2026072320}
CANONICAL_SIGNATURE = (
    "conditional-drawdown-vs-volatility-benchmark-v1|"
    "markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|"
    "benchmark=volatility-targeted-long|"
    "drawdown=nav-with-initial-one-over-running-peak-minus-one|"
    "metric=mean-deepest-ceil-5pct-drawdown-observations|tail-fraction=0.05|"
    "claim=strategy-minus-benchmark-conditional-drawdown>0-in-both-markets|"
    "resampling=paired-noncircular-moving-block-bootstrap-recompute-nav-and-drawdown|"
    "block-length=20-sessions|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072319,ETH-USDT:2026072320|candidate_count=1"
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
    return validated


def drawdown_series(returns: np.ndarray) -> np.ndarray:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or values.size < 1:
        raise ValueError("returns must be a non-empty one-dimensional array")
    if not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("returns must be finite and greater than -100%")

    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    running_peak = np.maximum.accumulate(nav)
    return (nav / running_peak - 1.0)[1:]


def conditional_drawdown_at_risk(returns: np.ndarray, tail_fraction: float) -> float:
    if not isinstance(tail_fraction, (int, float)) or isinstance(tail_fraction, bool):
        raise ValueError("tail_fraction must be a real number")
    if not math.isfinite(float(tail_fraction)) or not 0.0 < float(tail_fraction) < 1.0:
        raise ValueError("tail_fraction must be finite and strictly between zero and one")

    drawdowns = drawdown_series(returns)
    tail_count = math.ceil(drawdowns.size * float(tail_fraction))
    deepest = np.partition(drawdowns, tail_count - 1)[:tail_count]
    return float(np.mean(deepest))


def conditional_drawdown_delta(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    tail_fraction: float,
) -> dict[str, float]:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if strategy.shape != benchmark.shape:
        raise ValueError("strategy and benchmark returns must have identical shapes")
    if strategy.ndim != 1 or strategy.size < 1:
        raise ValueError("paired returns must be non-empty one-dimensional arrays")

    strategy_cdar = conditional_drawdown_at_risk(strategy, tail_fraction)
    benchmark_cdar = conditional_drawdown_at_risk(benchmark, tail_fraction)
    return {
        "strategy_conditional_drawdown": strategy_cdar,
        "benchmark_conditional_drawdown": benchmark_cdar,
        "observed_delta": strategy_cdar - benchmark_cdar,
    }


def moving_block_indices(
    observation_count: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if observation_count < 1:
        raise ValueError("observation_count must be positive")
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


def bootstrap_conditional_drawdown_delta(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    tail_fraction: float,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float]:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if strategy.shape != benchmark.shape:
        raise ValueError("strategy and benchmark returns must have identical shapes")
    if strategy.ndim != 1 or strategy.size < 1:
        raise ValueError("paired returns must be non-empty one-dimensional arrays")
    if not np.isfinite(strategy).all() or not np.isfinite(benchmark).all():
        raise ValueError("paired returns must be finite")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("confidence must be a real number")
    if not math.isfinite(float(confidence)) or not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be finite and strictly between zero and one")

    observed = conditional_drawdown_delta(
        strategy,
        benchmark,
        tail_fraction=tail_fraction,
    )

    rng = np.random.default_rng(seed)
    deltas = np.empty(resamples, dtype=float)
    for index in range(resamples):
        sample_indices = moving_block_indices(strategy.size, block_length, rng)
        sample = conditional_drawdown_delta(
            strategy[sample_indices],
            benchmark[sample_indices],
            tail_fraction=tail_fraction,
        )
        deltas[index] = sample["observed_delta"]

    alpha = 1.0 - float(confidence)
    lower, upper = np.quantile(deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        **observed,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "probability_delta_positive": float(np.mean(deltas > 0.0)),
    }


def analyze_market(artifact_dir: str | Path, market: str) -> dict[str, object]:
    returns_path = Path(artifact_dir) / market / "walk_forward_returns.csv"
    return_file_sha256 = verify_return_file_sha256(returns_path, market)
    returns = load_returns(returns_path)
    result = bootstrap_conditional_drawdown_delta(
        returns[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float),
        returns[BENCHMARK_RETURN_COLUMN].to_numpy(dtype=float),
        tail_fraction=TAIL_FRACTION,
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        confidence=CONFIDENCE,
        seed=SEEDS[market],
    )
    result["observations"] = len(returns)
    result["tail_observations"] = math.ceil(len(returns) * TAIL_FRACTION)
    result["period_start"] = returns["timestamp"].iloc[0].isoformat()
    result["period_end"] = returns["timestamp"].iloc[-1].isoformat()
    result["return_file_sha256"] = return_file_sha256
    result["passed"] = bool(result["ci_lower"] > 0.0)
    return result


def build_result(artifact_dir: str | Path) -> dict[str, object]:
    markets = {market: analyze_market(artifact_dir, market) for market in MARKETS}
    joint_passed = all(bool(markets[market]["passed"]) for market in MARKETS)
    failed_markets = [market for market in MARKETS if not bool(markets[market]["passed"])]
    rejection_reason = None
    if failed_markets:
        rejection_reason = (
            "The 95% paired moving-block-bootstrap lower bound for the strategy-minus-"
            "volatility-targeted-long conditional-drawdown delta was non-positive in: "
            + ", ".join(failed_markets)
        )

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "The adaptive strategy has less severe 5% conditional drawdown than the "
            "volatility-targeted-long benchmark in both BTC-USDT and ETH-USDT."
        ),
        "candidate_accounting": {
            "searched": 1,
            "passed": int(joint_passed),
            "rejected": int(not joint_passed),
        },
        "settings": {
            "benchmark": "volatility-targeted long",
            "conditional_drawdown_definition": (
                "mean of deepest ceil(tail_fraction * n) drawdown observations"
            ),
            "drawdown_definition": "NAV / running peak - 1, with initial NAV equal to 1",
            "tail_fraction": TAIL_FRACTION,
            "block_length_sessions": BLOCK_LENGTH,
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
            "source_workflow_run_id": 29980035904,
            "source_artifact_id": 8552853195,
            "source_artifact_name": "quant-research-source-1633-attempt-1",
            "source_artifact_sha256": (
                "462f6ea87ea0501916645e936282eeaecef9ed004723e6ec61a1ad63ced6c9e5"
            ),
            "source_code_commit": "a76d802ad92e63ab2dadadd95a1890a15f16e7cb",
            "source_main_base": "83d2b056381d087fdd54b7db39116e8551afab8a",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare strategy and volatility-targeted-long conditional drawdown."
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
