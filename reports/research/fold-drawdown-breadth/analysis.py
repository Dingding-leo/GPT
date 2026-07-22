from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
EXPECTED_FOLDS = 26
EXPECTED_FOLD_OBSERVATIONS = 90
BLOCK_LENGTH_FOLDS = 3
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072305, "ETH-USDT": 2026072306}
BENCHMARK_COLUMN = "benchmark_volatility_targeted_long_return"
CANONICAL_SIGNATURE = (
    "fold-drawdown-breadth-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|folds=26x90-nonoverlapping|"
    "comparison=strategy-vs-volatility-targeted-long|"
    "fold-metric=maximum-drawdown-from-fold-start-equity|"
    "delta=strategy-max-drawdown-minus-benchmark-max-drawdown|"
    "claim=mean-fold-drawdown-reduction-positive-in-both-markets|"
    "resampling=noncircular-moving-block-bootstrap-over-consecutive-fold-deltas|"
    "block-length=3-folds|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072305,ETH-USDT:2026072306|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def maximum_drawdown(returns: Sequence[float] | np.ndarray) -> float:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or len(values) < 1:
        raise ValueError("returns must be a non-empty one-dimensional sequence")
    if not np.isfinite(values).all() or bool((values <= -1.0).any()):
        raise ValueError("returns must be finite and greater than -100%")

    equity = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    running_peak = np.maximum.accumulate(equity)
    return float(np.min(equity / running_peak - 1.0))


def load_fold_drawdown_reductions(
    path: str | Path,
) -> tuple[pd.DataFrame, np.ndarray, np.ndarray, np.ndarray]:
    frame = pd.read_csv(path)
    required = {"timestamp", "fold", "strategy_return", BENCHMARK_COLUMN}
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

    folds = pd.to_numeric(frame["fold"], errors="raise")
    numeric_folds = folds.to_numpy(dtype=float)
    if (
        not np.isfinite(numeric_folds).all()
        or not np.equal(numeric_folds, np.floor(numeric_folds)).all()
    ):
        raise ValueError("fold identifiers must be finite integers")

    validated = pd.DataFrame(
        {
            "timestamp": timestamps,
            "fold": folds.astype(int).to_numpy(),
            "strategy_return": pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(
                dtype=float
            ),
            BENCHMARK_COLUMN: pd.to_numeric(frame[BENCHMARK_COLUMN], errors="raise").to_numpy(
                dtype=float
            ),
        }
    )
    return_columns = ["strategy_return", BENCHMARK_COLUMN]
    return_values = validated[return_columns].to_numpy(dtype=float)
    if not np.isfinite(return_values).all() or bool((return_values <= -1.0).any()):
        raise ValueError("strategy and benchmark returns must be finite and greater than -100%")

    grouped = validated.groupby("fold", sort=True, observed=True)
    fold_ids = np.array(list(grouped.groups), dtype=int)
    if len(fold_ids) == 0:
        raise ValueError("returns file must contain at least one fold")
    expected_ids = np.arange(fold_ids[0], fold_ids[0] + len(fold_ids), dtype=int)
    if not np.array_equal(fold_ids, expected_ids):
        raise ValueError("fold identifiers must be consecutive")

    strategy_drawdowns = []
    benchmark_drawdowns = []
    for _, fold_frame in grouped:
        strategy_drawdowns.append(maximum_drawdown(fold_frame["strategy_return"]))
        benchmark_drawdowns.append(maximum_drawdown(fold_frame[BENCHMARK_COLUMN]))

    strategy = np.asarray(strategy_drawdowns, dtype=float)
    benchmark = np.asarray(benchmark_drawdowns, dtype=float)
    return validated, strategy, benchmark, strategy - benchmark


def moving_block_mean_reduction(
    reductions: Sequence[float] | np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float | int]:
    values = np.asarray(reductions, dtype=float)
    if values.ndim != 1 or len(values) < 2:
        raise ValueError("reductions must be a one-dimensional sequence with at least two values")
    if not np.isfinite(values).all():
        raise ValueError("reductions must be finite")
    if isinstance(block_length, bool) or not isinstance(block_length, int):
        raise ValueError("block_length must be an integer")
    if block_length < 1 or block_length > len(values):
        raise ValueError("block_length must be between one and the fold count")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")

    rng = np.random.default_rng(seed)
    starts = np.arange(len(values) - block_length + 1, dtype=int)
    blocks_per_sample = math.ceil(len(values) / block_length)
    offsets = np.arange(block_length, dtype=int)
    sample_means = np.empty(resamples, dtype=float)

    for sample_index in range(resamples):
        selected_starts = rng.choice(starts, size=blocks_per_sample, replace=True)
        indices = (selected_starts[:, None] + offsets).reshape(-1)[: len(values)]
        sample_means[sample_index] = float(np.mean(values[indices]))

    alpha = 1.0 - confidence
    return {
        "folds": int(len(values)),
        "positive_reduction_folds": int(np.sum(values > 0.0)),
        "nonpositive_reduction_folds": int(np.sum(values <= 0.0)),
        "positive_reduction_share": float(np.mean(values > 0.0)),
        "mean_drawdown_reduction": float(np.mean(values)),
        "median_drawdown_reduction": float(np.median(values)),
        "confidence_lower": float(np.quantile(sample_means, alpha / 2.0)),
        "confidence_upper": float(np.quantile(sample_means, 1.0 - alpha / 2.0)),
        "probability_mean_reduction_positive": float(np.mean(sample_means > 0.0)),
    }


def analyze(artifact_dir: str | Path) -> dict[str, object]:
    root = Path(artifact_dir)
    market_results: dict[str, object] = {}
    return_hashes: dict[str, str] = {}

    for market in MARKETS:
        returns_path = root / market / "walk_forward_returns.csv"
        frame, strategy_drawdowns, benchmark_drawdowns, reductions = load_fold_drawdown_reductions(
            returns_path
        )
        fold_sizes = frame.groupby("fold", sort=True, observed=True).size().to_numpy(dtype=int)
        if len(reductions) != EXPECTED_FOLDS:
            raise ValueError(f"{market} must contain exactly {EXPECTED_FOLDS} folds")
        if not np.equal(fold_sizes, EXPECTED_FOLD_OBSERVATIONS).all():
            raise ValueError(
                f"{market} folds must each contain exactly "
                f"{EXPECTED_FOLD_OBSERVATIONS} observations"
            )

        statistics = moving_block_mean_reduction(
            reductions,
            block_length=BLOCK_LENGTH_FOLDS,
            resamples=RESAMPLES,
            confidence=CONFIDENCE,
            seed=SEEDS[market],
        )
        statistics["start"] = frame["timestamp"].iloc[0].isoformat()
        statistics["end"] = frame["timestamp"].iloc[-1].isoformat()
        statistics["strategy_fold_max_drawdowns"] = [float(value) for value in strategy_drawdowns]
        statistics["benchmark_fold_max_drawdowns"] = [float(value) for value in benchmark_drawdowns]
        statistics["fold_drawdown_reductions"] = [float(value) for value in reductions]
        market_results[market] = statistics
        return_hashes[market] = file_sha256(returns_path)

    passed = all(float(market_results[market]["confidence_lower"]) > 0.0 for market in MARKETS)
    rejection_reasons = []
    if not passed:
        for market in MARKETS:
            lower = float(market_results[market]["confidence_lower"])
            if lower <= 0.0:
                rejection_reasons.append(
                    f"{market} mean fold drawdown-reduction 95% lower bound "
                    f"{lower:.6f} is not positive"
                )

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "candidate_accounting": {
            "searched": 1,
            "passed": int(passed),
            "rejected": int(not passed),
        },
        "hypothesis": (
            "BTC-USDT and ETH-USDT each have a positive mean 90-session fold maximum-"
            "drawdown reduction versus volatility-targeted long, with a 95% moving-block-"
            "bootstrap lower bound above zero."
        ),
        "design": {
            "benchmark": "volatility-targeted long",
            "block_length_folds": BLOCK_LENGTH_FOLDS,
            "confidence": CONFIDENCE,
            "delta": "strategy maximum drawdown minus benchmark maximum drawdown",
            "expected_fold_observations": EXPECTED_FOLD_OBSERVATIONS,
            "expected_folds": EXPECTED_FOLDS,
            "fold_metric": "maximum drawdown from fold-start equity",
            "resamples": RESAMPLES,
            "seeds": SEEDS,
        },
        "markets": market_results,
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "development_markets": list(MARKETS),
            "source_workflow_run_id": 29940617808,
            "source_artifact_id": 8538033369,
            "source_artifact_name": "quant-research-source-1198-attempt-1",
            "source_artifact_sha256": (
                "30523ece44c47c7c3317f7a5f5e6273eb5886cccb213dae2cc177b86dce007df"
            ),
            "source_head_sha": "1f6e5a133cb012be1b8222b0e655b18f675fdb1e",
            "return_file_sha256": return_hashes,
        },
        "verdict": "pass" if passed else "reject",
        "rejection_reasons": rejection_reasons,
        "claim_boundary": (
            "Supported only as an unscaled development-market risk-control breadth effect; "
            "it is not evidence of alpha, volatility-normalized superiority, or untouched-"
            "holdout generalization."
        ),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test fold-level maximum-drawdown reduction versus volatility-targeted long."
    )
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = analyze(args.artifact_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"verdict={result['verdict']}")
    for market in MARKETS:
        statistics = result["markets"][market]
        print(
            f"{market} mean_reduction={statistics['mean_drawdown_reduction']:.6f} "
            f"ci=[{statistics['confidence_lower']:.6f},"
            f"{statistics['confidence_upper']:.6f}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
