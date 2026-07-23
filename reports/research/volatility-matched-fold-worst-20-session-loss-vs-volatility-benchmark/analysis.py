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
COMPLETE_FOLD_LENGTH = 90
LOSS_WINDOW = 20
FOLD_BLOCK_LENGTH = 3
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072321, "ETH-USDT": 2026072322}
CANONICAL_SIGNATURE = (
    "volatility-matched-fold-worst-20-session-loss-vs-volatility-benchmark-v1|"
    "markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|"
    "benchmark=volatility-targeted-long-scaled-within-each-complete-fold-to-strategy-sample-volatility|"
    "volatility=sample-standard-deviation-ddof1|complete-folds=26x90|"
    "trailing-short-fold=excluded|window=20-sessions|"
    "fold-metric=min-within-fold-compounded-20-session-return|"
    "delta=strategy-minus-volatility-matched-benchmark|aggregate=mean-fold-delta|"
    "claim=mean-fold-delta>0-in-both-markets|"
    "resampling=noncircular-moving-block-bootstrap-over-consecutive-complete-fold-deltas|"
    "block-length=3-folds|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072321,ETH-USDT:2026072322|candidate_count=1"
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


def _validated_fold_ids(values: pd.Series) -> np.ndarray:
    numeric = pd.to_numeric(values, errors="raise").to_numpy(dtype=float)
    if not np.isfinite(numeric).all() or np.any(numeric < 1.0):
        raise ValueError("fold ids must be finite positive integers")
    integer = numeric.astype(np.int64)
    if not np.array_equal(numeric, integer.astype(float)):
        raise ValueError("fold ids must be integers")
    if np.any(np.diff(integer) < 0):
        raise ValueError("fold ids must be nondecreasing")
    observed = np.unique(integer)
    expected = np.arange(observed[0], observed[-1] + 1, dtype=np.int64)
    if observed[0] != 1 or not np.array_equal(observed, expected):
        raise ValueError("fold ids must be contiguous and start at one")
    return integer


def load_returns(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {
        "timestamp",
        "fold",
        STRATEGY_RETURN_COLUMN,
        BENCHMARK_RETURN_COLUMN,
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")
    validated = pd.DataFrame(
        {
            "timestamp": _validated_timestamps(frame["timestamp"]),
            "fold": _validated_fold_ids(frame["fold"]),
        }
    )
    for column in (STRATEGY_RETURN_COLUMN, BENCHMARK_RETURN_COLUMN):
        values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(values <= -1.0):
            raise ValueError(f"{column} must contain finite returns greater than -100%")
        validated[column] = values
    return validated


def complete_fold_ids(frame: pd.DataFrame, *, fold_length: int) -> list[int]:
    if isinstance(fold_length, bool) or not isinstance(fold_length, int) or fold_length < 1:
        raise ValueError("fold_length must be a positive integer")
    sizes = frame.groupby("fold", sort=True).size()
    if sizes.empty:
        raise ValueError("returns must contain at least one fold")
    oversized = sizes[sizes > fold_length]
    if not oversized.empty:
        raise ValueError(f"folds exceed the declared complete length: {oversized.to_dict()}")
    incomplete = sizes[sizes < fold_length]
    if len(incomplete) > 1 or (
        len(incomplete) == 1 and int(incomplete.index[0]) != int(sizes.index[-1])
    ):
        raise ValueError("only one trailing shorter fold may be excluded")
    complete = [int(fold) for fold, size in sizes.items() if int(size) == fold_length]
    if not complete:
        raise ValueError("returns must contain at least one complete fold")
    return complete


def sample_volatility_scale(strategy_returns: np.ndarray, benchmark_returns: np.ndarray) -> float:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if strategy.ndim != 1 or benchmark.ndim != 1 or strategy.size != benchmark.size:
        raise ValueError("strategy and benchmark returns must be aligned one-dimensional arrays")
    if strategy.size < 2:
        raise ValueError("at least two aligned returns are required for sample volatility")
    if not np.isfinite(strategy).all() or not np.isfinite(benchmark).all():
        raise ValueError("returns must be finite")
    strategy_volatility = float(np.std(strategy, ddof=1))
    benchmark_volatility = float(np.std(benchmark, ddof=1))
    if not math.isfinite(benchmark_volatility) or benchmark_volatility <= 0.0:
        raise ValueError("benchmark sample volatility must be finite and positive")
    scale = strategy_volatility / benchmark_volatility
    if not math.isfinite(scale) or scale < 0.0:
        raise ValueError("volatility scale must be finite and non-negative")
    return scale


def worst_compounded_window_return(returns: np.ndarray, *, window: int) -> float:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or values.size < 1:
        raise ValueError("returns must be a non-empty one-dimensional array")
    if not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("returns must be finite and greater than -100%")
    if isinstance(window, bool) or not isinstance(window, int):
        raise ValueError("window must be an integer")
    if window < 1 or window > values.size:
        raise ValueError("window must be between one and the return count")
    windows = np.lib.stride_tricks.sliding_window_view(values, window)
    compounded = np.prod(1.0 + windows, axis=1) - 1.0
    return float(np.min(compounded))


def fold_worst_window_deltas(
    frame: pd.DataFrame,
    *,
    fold_length: int,
    window: int,
) -> pd.DataFrame:
    rows: list[dict[str, float | int]] = []
    for fold in complete_fold_ids(frame, fold_length=fold_length):
        fold_frame = frame.loc[frame["fold"] == fold]
        strategy = fold_frame[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float)
        benchmark = fold_frame[BENCHMARK_RETURN_COLUMN].to_numpy(dtype=float)
        scale = sample_volatility_scale(strategy, benchmark)
        scaled_benchmark = benchmark * scale
        if np.any(scaled_benchmark <= -1.0) or not np.isfinite(scaled_benchmark).all():
            raise ValueError(
                "volatility-matched benchmark returns must remain finite and above -100%"
            )
        strategy_worst = worst_compounded_window_return(strategy, window=window)
        benchmark_worst = worst_compounded_window_return(scaled_benchmark, window=window)
        rows.append(
            {
                "fold": fold,
                "strategy_sample_volatility": float(np.std(strategy, ddof=1)),
                "benchmark_sample_volatility": float(np.std(benchmark, ddof=1)),
                "benchmark_volatility_scale": scale,
                "strategy_worst_window_return": strategy_worst,
                "volatility_matched_benchmark_worst_window_return": benchmark_worst,
                "delta": strategy_worst - benchmark_worst,
            }
        )
    return pd.DataFrame(rows)


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
        raise ValueError("block_length must be between one and observation_count")
    block_count = math.ceil(observation_count / block_length)
    starts = rng.integers(0, observation_count - block_length + 1, size=block_count)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observation_count]


def bootstrap_mean_delta(
    deltas: np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float]:
    values = np.asarray(deltas, dtype=float)
    if values.ndim != 1 or values.size < 1 or not np.isfinite(values).all():
        raise ValueError("deltas must be a non-empty finite one-dimensional array")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("confidence must be a real number")
    if not math.isfinite(float(confidence)) or not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be finite and strictly between zero and one")
    rng = np.random.default_rng(seed)
    sampled_means = np.empty(resamples, dtype=float)
    for index in range(resamples):
        sample_indices = moving_block_indices(values.size, block_length, rng)
        sampled_means[index] = float(np.mean(values[sample_indices]))
    alpha = 1.0 - float(confidence)
    lower, upper = np.quantile(sampled_means, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "observed_mean_delta": float(np.mean(values)),
        "median_fold_delta": float(np.median(values)),
        "positive_fold_count": int(np.sum(values > 0.0)),
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "probability_mean_delta_positive": float(np.mean(sampled_means > 0.0)),
    }


def analyze_market(artifact_dir: str | Path, market: str) -> dict[str, object]:
    returns_path = Path(artifact_dir) / market / "walk_forward_returns.csv"
    return_file_sha256 = verify_return_file_sha256(returns_path, market)
    returns = load_returns(returns_path)
    fold_metrics = fold_worst_window_deltas(
        returns,
        fold_length=COMPLETE_FOLD_LENGTH,
        window=LOSS_WINDOW,
    )
    bootstrap = bootstrap_mean_delta(
        fold_metrics["delta"].to_numpy(dtype=float),
        block_length=FOLD_BLOCK_LENGTH,
        resamples=RESAMPLES,
        confidence=CONFIDENCE,
        seed=SEEDS[market],
    )
    complete_folds = int(len(fold_metrics))
    excluded_rows = int(len(returns) - complete_folds * COMPLETE_FOLD_LENGTH)
    return {
        **bootstrap,
        "complete_folds": complete_folds,
        "excluded_trailing_rows": excluded_rows,
        "rolling_windows_per_fold": COMPLETE_FOLD_LENGTH - LOSS_WINDOW + 1,
        "mean_benchmark_volatility_scale": float(fold_metrics["benchmark_volatility_scale"].mean()),
        "median_benchmark_volatility_scale": float(
            fold_metrics["benchmark_volatility_scale"].median()
        ),
        "strategy_mean_fold_worst_window_return": float(
            fold_metrics["strategy_worst_window_return"].mean()
        ),
        "volatility_matched_benchmark_mean_fold_worst_window_return": float(
            fold_metrics["volatility_matched_benchmark_worst_window_return"].mean()
        ),
        "fold_metrics": fold_metrics.to_dict(orient="records"),
        "period_start": returns["timestamp"].iloc[0].isoformat(),
        "period_end": returns["timestamp"].iloc[-1].isoformat(),
        "return_file_sha256": return_file_sha256,
        "passed": bool(bootstrap["ci_lower"] > 0.0),
    }


def build_result(artifact_dir: str | Path) -> dict[str, object]:
    markets = {market: analyze_market(artifact_dir, market) for market in MARKETS}
    joint_passed = all(bool(markets[market]["passed"]) for market in MARKETS)
    failed_markets = [market for market in MARKETS if not bool(markets[market]["passed"])]
    rejection_reason = None
    if failed_markets:
        rejection_reason = (
            "The 95% complete-fold moving-block-bootstrap lower bound for the mean "
            "strategy-minus-volatility-matched-benchmark worst 20-session return delta "
            "was non-positive in: " + ", ".join(failed_markets)
        )
    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "The adaptive strategy has a less severe mean within-fold worst compounded "
            "20-session return than a within-fold volatility-matched volatility-targeted-long "
            "benchmark in both BTC-USDT and ETH-USDT."
        ),
        "candidate_accounting": {
            "searched": 1,
            "passed": int(joint_passed),
            "rejected": int(not joint_passed),
        },
        "settings": {
            "benchmark": "volatility-targeted long",
            "benchmark_volatility_matching": (
                "scale each complete fold by strategy sample std / benchmark sample std, ddof=1"
            ),
            "complete_fold_length_sessions": COMPLETE_FOLD_LENGTH,
            "trailing_short_fold_policy": "exclude exactly one trailing shorter fold",
            "loss_window_sessions": LOSS_WINDOW,
            "fold_metric": "minimum within-fold compounded window return",
            "aggregate_metric": "mean strategy-minus-volatility-matched-benchmark fold delta",
            "fold_block_length": FOLD_BLOCK_LENGTH,
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
            "source_workflow_run_id": 29982033676,
            "source_artifact_id": 8553558024,
            "source_artifact_name": "quant-research-source-1679-attempt-1",
            "source_artifact_sha256": (
                "382f20d2350ebd5cb79aafdf3c901eda4ec0f1663c33d0bae9b70a920d3c82b7"
            ),
            "source_code_commit": "c3bd405ac7ddd6a7fd6d8eff8d9372a05a8855b4",
            "source_main_commit": "2cb492b66873bccbf5535c8f3721feb3ee52c880",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare strategy and within-fold volatility-matched volatility-targeted-long "
            "worst 20-session losses."
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
