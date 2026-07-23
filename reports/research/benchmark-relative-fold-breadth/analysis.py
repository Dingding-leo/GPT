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
EXPECTED_COMPLETE_FOLDS = 26
EXPECTED_FOLD_OBSERVATIONS = 90
BLOCK_LENGTH_FOLDS = 3
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072310, "ETH-USDT": 2026072311}
BENCHMARK_COLUMN = "benchmark_volatility_targeted_long_return"
CANONICAL_SIGNATURE = (
    "benchmark-relative-fold-breadth-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|benchmark=volatility-targeted-long|"
    "complete-folds=26x90|trailing-incomplete-fold=excluded|"
    "fold-metric=compounded-strategy-return-minus-compounded-benchmark-return|"
    "success=delta>0|claim=outperformance-share>0.5-in-both-markets|"
    "resampling=noncircular-moving-block-bootstrap-over-consecutive-complete-folds|"
    "block-length=3-folds|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072310,ETH-USDT:2026072311|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compounded_return(values: pd.Series) -> float:
    return float(np.prod(1.0 + values.to_numpy(dtype=float)) - 1.0)


def load_complete_fold_deltas(
    path: str | Path,
    *,
    expected_complete_folds: int = EXPECTED_COMPLETE_FOLDS,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    source = Path(path)
    frame = pd.read_csv(source)
    required = {"timestamp", "fold", "strategy_return", BENCHMARK_COLUMN}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")

    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("returns timestamps must be unique and strictly increasing")

    folds = pd.to_numeric(frame["fold"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(folds).all() or not np.equal(folds, np.floor(folds)).all():
        raise ValueError("fold identifiers must be finite integers")

    strategy = pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(dtype=float)
    benchmark = pd.to_numeric(frame[BENCHMARK_COLUMN], errors="raise").to_numpy(dtype=float)
    for name, values in (("strategy", strategy), ("benchmark", benchmark)):
        if not np.isfinite(values).all() or np.any(values <= -1.0):
            raise ValueError(f"{name} returns must be finite and greater than -100%")

    validated = pd.DataFrame(
        {
            "timestamp": timestamps,
            "fold": folds.astype(int),
            "strategy_return": strategy,
            BENCHMARK_COLUMN: benchmark,
        }
    )
    grouped = validated.groupby("fold", sort=True, observed=True)
    fold_ids = np.array(list(grouped.groups), dtype=int)
    if len(fold_ids) == 0 or not np.array_equal(fold_ids, np.arange(1, len(fold_ids) + 1)):
        raise ValueError("fold identifiers must be consecutive and start at one")

    fold_sizes = grouped.size()
    complete_ids = fold_sizes.index[fold_sizes == EXPECTED_FOLD_OBSERVATIONS].to_numpy(dtype=int)
    incomplete_ids = fold_sizes.index[fold_sizes != EXPECTED_FOLD_OBSERVATIONS].to_numpy(dtype=int)
    if len(incomplete_ids) > 1 or (
        len(incomplete_ids) == 1 and incomplete_ids[0] != fold_ids[-1]
    ):
        raise ValueError("only one trailing incomplete fold may be excluded")
    if len(complete_ids) != expected_complete_folds:
        raise ValueError(
            f"expected exactly {expected_complete_folds} complete folds, found {len(complete_ids)}"
        )
    if not np.array_equal(complete_ids, np.arange(1, expected_complete_folds + 1)):
        raise ValueError("the complete folds must be the first consecutive folds")

    records: list[dict[str, float | int | str | bool]] = []
    for fold_id in complete_ids:
        fold = grouped.get_group(int(fold_id))
        strategy_return = _compounded_return(fold["strategy_return"])
        benchmark_return = _compounded_return(fold[BENCHMARK_COLUMN])
        delta = strategy_return - benchmark_return
        records.append(
            {
                "fold": int(fold_id),
                "start": fold["timestamp"].iloc[0].isoformat(),
                "end": fold["timestamp"].iloc[-1].isoformat(),
                "strategy_compounded_return": strategy_return,
                "benchmark_compounded_return": benchmark_return,
                "relative_return_delta": delta,
                "outperformed": bool(delta > 0.0),
            }
        )

    return validated, pd.DataFrame.from_records(records)


def moving_block_outperformance_share(
    relative_returns: Sequence[float] | np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float | int]:
    values = np.asarray(relative_returns, dtype=float)
    if values.ndim != 1 or len(values) < 2:
        raise ValueError("relative returns must be one-dimensional with at least two values")
    if not np.isfinite(values).all():
        raise ValueError("relative returns must be finite")
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
    shares = np.empty(resamples, dtype=float)

    for sample_index in range(resamples):
        selected_starts = rng.choice(starts, size=blocks_per_sample, replace=True)
        indices = (selected_starts[:, None] + offsets).reshape(-1)[: len(values)]
        shares[sample_index] = float(np.mean(values[indices] > 0.0))

    alpha = 1.0 - confidence
    return {
        "complete_folds": int(len(values)),
        "outperforming_folds": int(np.sum(values > 0.0)),
        "outperformance_share": float(np.mean(values > 0.0)),
        "median_relative_fold_return": float(np.median(values)),
        "mean_relative_fold_return": float(np.mean(values)),
        "confidence_lower": float(np.quantile(shares, alpha / 2.0)),
        "confidence_upper": float(np.quantile(shares, 1.0 - alpha / 2.0)),
        "probability_share_above_half": float(np.mean(shares > 0.5)),
    }


def analyze(artifact_dir: str | Path) -> dict[str, object]:
    root = Path(artifact_dir)
    market_results: dict[str, object] = {}
    return_hashes: dict[str, str] = {}

    for market in MARKETS:
        returns_path = root / market / "walk_forward_returns.csv"
        frame, fold_records = load_complete_fold_deltas(returns_path)
        relative_returns = fold_records["relative_return_delta"].to_numpy(dtype=float)
        statistics = moving_block_outperformance_share(
            relative_returns,
            block_length=BLOCK_LENGTH_FOLDS,
            resamples=RESAMPLES,
            confidence=CONFIDENCE,
            seed=SEEDS[market],
        )
        statistics["source_observations"] = int(len(frame))
        statistics["source_start"] = frame["timestamp"].iloc[0].isoformat()
        statistics["source_end"] = frame["timestamp"].iloc[-1].isoformat()
        statistics["complete_fold_start"] = str(fold_records["start"].iloc[0])
        statistics["complete_fold_end"] = str(fold_records["end"].iloc[-1])
        statistics["trailing_incomplete_observations"] = int(
            len(frame) - EXPECTED_COMPLETE_FOLDS * EXPECTED_FOLD_OBSERVATIONS
        )
        statistics["fold_records"] = fold_records.to_dict(orient="records")
        market_results[market] = statistics
        return_hashes[market] = file_sha256(returns_path)

    passed = all(float(market_results[market]["confidence_lower"]) > 0.5 for market in MARKETS)
    rejection_reasons = []
    if not passed:
        for market in MARKETS:
            lower = float(market_results[market]["confidence_lower"])
            if lower <= 0.5:
                rejection_reasons.append(
                    f"{market} outperformance-share 95% lower bound {lower:.6f} is not above 0.5"
                )

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "candidate_accounting": {
            "searched": 1,
            "passed": int(passed),
            "rejected": int(not passed),
        },
        "hypothesis": (
            "BTC-USDT and ETH-USDT each outperform volatility-targeted long in more than "
            "half of their complete 90-session rolling OOS folds, with a 95% moving-block-"
            "bootstrap lower bound above 0.5."
        ),
        "design": {
            "benchmark": "volatility-targeted long",
            "block_length_folds": BLOCK_LENGTH_FOLDS,
            "confidence": CONFIDENCE,
            "expected_complete_folds": EXPECTED_COMPLETE_FOLDS,
            "expected_fold_observations": EXPECTED_FOLD_OBSERVATIONS,
            "fold_metric": (
                "compounded net strategy return minus compounded net "
                "volatility-targeted-long return"
            ),
            "fold_success_rule": "relative fold return delta > 0",
            "resamples": RESAMPLES,
            "seeds": SEEDS,
            "trailing_incomplete_fold_policy": (
                "exclude one trailing fold shorter than 90 observations"
            ),
        },
        "markets": market_results,
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "development_markets": list(MARKETS),
            "source_workflow_run_id": 29967772412,
            "source_artifact_id": 8548502306,
            "source_artifact_name": "quant-research-source-1473-attempt-1",
            "source_artifact_sha256": (
                "79cd3100c2f41d42d4fc61c1e63e765c5ec4c6b9645457c9d24469121c88b1be"
            ),
            "source_head_sha": "b6a15182dd4a688208b1c737f97a24dd295bf34c",
            "return_file_sha256": return_hashes,
        },
        "verdict": "pass" if passed else "reject",
        "rejection_reasons": rejection_reasons,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test benchmark-relative outperformance breadth across complete OOS folds."
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
            f"{market} outperforming_folds={statistics['outperforming_folds']}/"
            f"{statistics['complete_folds']} share={statistics['outperformance_share']:.6f} "
            f"ci=[{statistics['confidence_lower']:.6f},"
            f"{statistics['confidence_upper']:.6f}]"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
