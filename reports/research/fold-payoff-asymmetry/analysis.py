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
SEEDS = {"BTC-USDT": 2026072303, "ETH-USDT": 2026072304}
CANONICAL_SIGNATURE = (
    "fold-payoff-asymmetry-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|folds=26x90-nonoverlapping|"
    "fold-metric=compounded-net-return|"
    "payoff-ratio=sum-positive-fold-returns/abs(sum-negative-fold-returns)|"
    "claim=fold-payoff-ratio>1-in-both-markets|"
    "resampling=noncircular-moving-block-bootstrap-over-consecutive-folds|"
    "block-length=3-folds|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072303,ETH-USDT:2026072304|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_fold_returns(path: str | Path) -> tuple[pd.DataFrame, np.ndarray]:
    frame = pd.read_csv(path)
    required = {"timestamp", "fold", "strategy_return"}
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

    returns = pd.to_numeric(frame["strategy_return"], errors="raise").astype(float)
    if not np.isfinite(returns.to_numpy()).all() or (returns <= -1.0).any():
        raise ValueError("strategy returns must be finite and greater than -100%")

    validated = pd.DataFrame(
        {
            "timestamp": timestamps,
            "fold": folds.astype(int).to_numpy(),
            "strategy_return": returns.to_numpy(),
        }
    )
    grouped = validated.groupby("fold", sort=True, observed=True)
    fold_ids = np.array(list(grouped.groups), dtype=int)
    if len(fold_ids) == 0:
        raise ValueError("returns file must contain at least one fold")
    expected_ids = np.arange(fold_ids[0], fold_ids[0] + len(fold_ids), dtype=int)
    if not np.array_equal(fold_ids, expected_ids):
        raise ValueError("fold identifiers must be consecutive")

    fold_returns = grouped["strategy_return"].apply(
        lambda values: float(np.prod(1.0 + values.to_numpy(dtype=float)) - 1.0)
    )
    return validated, fold_returns.to_numpy(dtype=float)


def fold_payoff_ratio(fold_returns: Sequence[float] | np.ndarray) -> float:
    values = np.asarray(fold_returns, dtype=float)
    if values.ndim != 1 or len(values) < 2:
        raise ValueError("fold returns must be a one-dimensional sequence with at least two values")
    if not np.isfinite(values).all():
        raise ValueError("fold returns must be finite")

    total_gains = float(values[values > 0.0].sum())
    total_losses = float(-values[values < 0.0].sum())
    if total_gains <= 0.0 or total_losses <= 0.0:
        raise ValueError("fold returns must contain at least one gain and one loss")
    return total_gains / total_losses


def moving_block_payoff_ratio(
    fold_returns: Sequence[float] | np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float | int]:
    values = np.asarray(fold_returns, dtype=float)
    point_ratio = fold_payoff_ratio(values)
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
    ratios = np.empty(resamples, dtype=float)

    for sample_index in range(resamples):
        selected_starts = rng.choice(starts, size=blocks_per_sample, replace=True)
        indices = (selected_starts[:, None] + offsets).reshape(-1)[: len(values)]
        sample = values[indices]
        gains = float(sample[sample > 0.0].sum())
        losses = float(-sample[sample < 0.0].sum())
        ratios[sample_index] = gains / losses if losses > 0.0 else math.inf

    alpha = 1.0 - confidence
    return {
        "folds": int(len(values)),
        "positive_folds": int(np.sum(values > 0.0)),
        "negative_folds": int(np.sum(values < 0.0)),
        "zero_folds": int(np.sum(values == 0.0)),
        "total_positive_fold_return": float(values[values > 0.0].sum()),
        "total_absolute_negative_fold_return": float(-values[values < 0.0].sum()),
        "fold_payoff_ratio": point_ratio,
        "confidence_lower": float(np.quantile(ratios, alpha / 2.0)),
        "confidence_upper": float(np.quantile(ratios, 1.0 - alpha / 2.0)),
        "probability_ratio_above_one": float(np.mean(ratios > 1.0)),
    }


def analyze(artifact_dir: str | Path) -> dict[str, object]:
    root = Path(artifact_dir)
    market_results: dict[str, object] = {}
    return_hashes: dict[str, str] = {}

    for market in MARKETS:
        returns_path = root / market / "walk_forward_returns.csv"
        frame, fold_returns = load_fold_returns(returns_path)
        fold_sizes = frame.groupby("fold", sort=True, observed=True).size().to_numpy(dtype=int)
        if len(fold_returns) != EXPECTED_FOLDS:
            raise ValueError(f"{market} must contain exactly {EXPECTED_FOLDS} folds")
        if not np.equal(fold_sizes, EXPECTED_FOLD_OBSERVATIONS).all():
            raise ValueError(
                f"{market} folds must each contain exactly "
                f"{EXPECTED_FOLD_OBSERVATIONS} observations"
            )

        statistics = moving_block_payoff_ratio(
            fold_returns,
            block_length=BLOCK_LENGTH_FOLDS,
            resamples=RESAMPLES,
            confidence=CONFIDENCE,
            seed=SEEDS[market],
        )
        statistics["start"] = frame["timestamp"].iloc[0].isoformat()
        statistics["end"] = frame["timestamp"].iloc[-1].isoformat()
        statistics["fold_returns"] = [float(value) for value in fold_returns]
        market_results[market] = statistics
        return_hashes[market] = file_sha256(returns_path)

    passed = all(float(market_results[market]["confidence_lower"]) > 1.0 for market in MARKETS)
    rejection_reasons = []
    if not passed:
        for market in MARKETS:
            lower = float(market_results[market]["confidence_lower"])
            if lower <= 1.0:
                rejection_reasons.append(
                    f"{market} fold-payoff-ratio 95% lower bound {lower:.6f} is not above 1"
                )

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "candidate_accounting": {
            "searched": 1,
            "passed": int(passed),
            "rejected": int(not passed),
        },
        "hypothesis": (
            "BTC-USDT and ETH-USDT each have aggregate positive compounded OOS fold returns "
            "that exceed the absolute aggregate negative fold returns, with a 95% "
            "moving-block-bootstrap lower bound for the fold payoff ratio above one."
        ),
        "design": {
            "block_length_folds": BLOCK_LENGTH_FOLDS,
            "confidence": CONFIDENCE,
            "expected_fold_observations": EXPECTED_FOLD_OBSERVATIONS,
            "expected_folds": EXPECTED_FOLDS,
            "fold_metric": "compounded net strategy return",
            "payoff_ratio": "sum(positive fold returns) / abs(sum(negative fold returns))",
            "resamples": RESAMPLES,
            "seeds": SEEDS,
        },
        "markets": market_results,
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "development_markets": list(MARKETS),
            "source_workflow_run_id": 29936458263,
            "source_artifact_id": 8536340303,
            "source_artifact_name": "quant-research-source-1159-attempt-1",
            "source_artifact_sha256": (
                "83eb247b7d848ddc61ebbb914e937268af0352ed1cbb11371877e6d947de1fb3"
            ),
            "source_head_sha": "88a8280d3a29153ab9fdd976ffb68899c975a908",
            "return_file_sha256": return_hashes,
        },
        "verdict": "pass" if passed else "reject",
        "rejection_reasons": rejection_reasons,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test whether winning OOS folds outweigh losing OOS folds."
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
            f"{market} ratio={statistics['fold_payoff_ratio']:.6f} "
            f"ci=[{statistics['confidence_lower']:.6f},"
            f"{statistics['confidence_upper']:.6f}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
