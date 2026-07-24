from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MARKETS = {
    "BTC-USDT": {
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "36c13d611e09ddeb65788ea2f597979e763aa797ef79b0fd341ef9aba33b3eca",
        "seed": 20260722,
    },
    "ETH-USDT": {
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "d51ee25fe582da2ffd1a234372758b8eee5c05bdfdce3a4021716bc9e781628e",
        "seed": 20260723,
    },
}
ANNUALIZATION = 365
FOLD_COUNT = 26
TEST_BARS = 90
EXCLUDED_OBSERVATIONS_PER_FOLD = 1
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
CANDIDATE_COUNT = 1
CANONICAL_SIGNATURE = (
    "fold-boundary-exclusion-consistency-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|stress=exclude-first-observation-each-fold|"
    "metric=annualized-arithmetic-mean-net-return|annualization=365|"
    "resampling=within-fold-noncircular-moving-block|block=20|resamples=2000|"
    "confidence=0.95|seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_hash(path: Path, expected_sha256: str, *, label: str) -> None:
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"{label} hash mismatch for {path}: expected {expected_sha256}, got {actual_sha256}"
        )


def validate_report(path: Path, expected_sha256: str) -> dict[str, Any]:
    _validate_hash(path, expected_sha256, label="walk-forward report")
    report = json.loads(path.read_text(encoding="utf-8"))
    settings = report.get("settings")
    folds = report.get("folds")
    if not isinstance(settings, dict) or not isinstance(folds, list):
        raise ValueError("walk-forward report must contain settings and folds")
    base_config = settings.get("base_config")
    if not isinstance(base_config, dict):
        raise ValueError("walk-forward report must contain settings.base_config")

    expected_settings = {
        "annualization": ANNUALIZATION,
        "candidate_count": 27,
        "cost_multipliers": [1.0, 2.0, 4.0],
        "non_overlapping_test_folds": True,
        "selection_bars": 730,
        "test_bars": TEST_BARS,
        "transaction_cost_bps": 10.0,
    }
    observed_settings = {
        "annualization": base_config.get("annualization"),
        "candidate_count": settings.get("candidate_count"),
        "cost_multipliers": settings.get("cost_multipliers"),
        "non_overlapping_test_folds": settings.get("non_overlapping_test_folds"),
        "selection_bars": settings.get("selection_bars"),
        "test_bars": settings.get("test_bars"),
        "transaction_cost_bps": base_config.get("transaction_cost_bps"),
    }
    if observed_settings != expected_settings:
        raise ValueError(
            "walk-forward settings do not match the predeclared fold-boundary test: "
            f"expected {expected_settings}, got {observed_settings}"
        )
    if len(folds) != FOLD_COUNT:
        raise ValueError(f"expected {FOLD_COUNT} folds, got {len(folds)}")
    expected_fold_ids = list(range(1, FOLD_COUNT + 1))
    if [fold.get("fold") for fold in folds] != expected_fold_ids:
        raise ValueError("walk-forward report fold identifiers must be consecutive")
    if any(fold.get("test_metrics", {}).get("observations") != TEST_BARS for fold in folds):
        raise ValueError(f"every walk-forward test fold must contain {TEST_BARS} observations")
    return report


def _explicit_utc_timestamps(values: pd.Series) -> pd.Series:
    timestamps: list[pd.Timestamp] = []
    for value in values:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamps must contain explicit timezone information")
        timestamps.append(timestamp)
    return pd.Series(pd.to_datetime(timestamps, utc=True), index=values.index)


def validate_returns(path: Path, expected_sha256: str) -> pd.DataFrame:
    _validate_hash(path, expected_sha256, label="walk-forward returns")
    frame = pd.read_csv(path)
    required = {"timestamp", "fold", "strategy_return"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    timestamps = _explicit_utc_timestamps(frame["timestamp"])
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = timestamps.diff().iloc[1:]
        if not intervals.eq(pd.Timedelta(days=1)).all():
            raise ValueError("timestamps must have exact daily cadence")

    folds = pd.to_numeric(frame["fold"], errors="coerce")
    returns = pd.to_numeric(frame["strategy_return"], errors="coerce")
    if folds.isna().any() or returns.isna().any():
        raise ValueError("fold and strategy_return must contain numeric values")
    if not np.isfinite(returns.to_numpy(dtype=float)).all():
        raise ValueError("strategy_return must contain finite values")
    if np.any(returns.to_numpy(dtype=float) <= -1.0):
        raise ValueError("strategy_return must be greater than -1")
    if not np.equal(folds.to_numpy(dtype=float), folds.to_numpy(dtype=int)).all():
        raise ValueError("fold identifiers must be integers")

    validated = pd.DataFrame(
        {
            "timestamp": timestamps,
            "fold": folds.to_numpy(dtype=int),
            "strategy_return": returns.to_numpy(dtype=float),
        }
    )
    expected_fold_ids = list(range(1, FOLD_COUNT + 1))
    if sorted(validated["fold"].unique().tolist()) != expected_fold_ids:
        raise ValueError("returns must contain every consecutive predeclared fold")
    fold_sizes = validated.groupby("fold", sort=True).size()
    if not fold_sizes.eq(TEST_BARS).all():
        raise ValueError(f"every returns fold must contain exactly {TEST_BARS} observations")
    if not validated["fold"].is_monotonic_increasing:
        raise ValueError("fold identifiers must be chronologically non-decreasing")
    return validated


def validate_report_alignment(frame: pd.DataFrame, report: dict[str, Any]) -> None:
    folds = report["folds"]
    for fold_report, (fold_id, fold_frame) in zip(
        folds,
        frame.groupby("fold", sort=True),
        strict=True,
    ):
        if fold_report["fold"] != fold_id:
            raise ValueError("report and returns fold identifiers do not align")
        observed_start = fold_frame["timestamp"].iloc[0].isoformat()
        observed_end = fold_frame["timestamp"].iloc[-1].isoformat()
        if observed_start != fold_report["test_start"]:
            raise ValueError(f"fold {fold_id} test_start does not align with returns")
        if observed_end != fold_report["test_end"]:
            raise ValueError(f"fold {fold_id} test_end does not align with returns")


def fold_interior_segments(frame: pd.DataFrame) -> tuple[np.ndarray, ...]:
    segments: list[np.ndarray] = []
    for _, fold_frame in frame.groupby("fold", sort=True):
        values = fold_frame["strategy_return"].to_numpy(dtype=float)
        if len(values) <= EXCLUDED_OBSERVATIONS_PER_FOLD:
            raise ValueError("fold is too short after excluding its boundary observation")
        segments.append(values[EXCLUDED_OBSERVATIONS_PER_FOLD:].copy())
    if not segments:
        raise ValueError("at least one fold-interior segment is required")
    return tuple(segments)


def resample_segment_non_circular(
    values: np.ndarray,
    *,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if values.ndim != 1 or len(values) < block_length:
        raise ValueError("segment must be one-dimensional and at least one block long")
    output = np.empty(len(values), dtype=float)
    written = 0
    maximum_start = len(values) - block_length
    while written < len(values):
        start = int(rng.integers(0, maximum_start + 1))
        take = min(block_length, len(values) - written)
        output[written : written + take] = values[start : start + take]
        written += take
    return output


def segmented_moving_block_mean_distribution(
    segments: Sequence[np.ndarray],
    *,
    block_length: int,
    resamples: int,
    annualization: int,
    seed: int,
) -> np.ndarray:
    if not segments:
        raise ValueError("segments cannot be empty")
    if block_length < 2 or resamples < 1 or annualization < 2:
        raise ValueError("block_length, resamples, and annualization must be valid")
    observation_count = sum(len(segment) for segment in segments)
    if observation_count == 0:
        raise ValueError("segments cannot be empty")

    rng = np.random.default_rng(seed)
    distribution = np.empty(resamples, dtype=float)
    for resample_index in range(resamples):
        total = 0.0
        for segment in segments:
            sampled = resample_segment_non_circular(
                segment,
                block_length=block_length,
                rng=rng,
            )
            total += float(sampled.sum())
        distribution[resample_index] = total / observation_count * annualization
    return distribution


def analyze_market(frame: pd.DataFrame, *, seed: int) -> dict[str, Any]:
    segments = fold_interior_segments(frame)
    interior = np.concatenate(segments)
    full_returns = frame["strategy_return"].to_numpy(dtype=float)
    boundary = frame.groupby("fold", sort=True)["strategy_return"].first().to_numpy(dtype=float)
    distribution = segmented_moving_block_mean_distribution(
        segments,
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        annualization=ANNUALIZATION,
        seed=seed,
    )
    alpha = 1.0 - CONFIDENCE
    lower, upper = np.quantile(distribution, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "seed": seed,
        "folds": len(segments),
        "full_observations": len(full_returns),
        "boundary_observations_removed": len(boundary),
        "interior_observations": len(interior),
        "full_annualized_mean": float(full_returns.mean() * ANNUALIZATION),
        "boundary_annualized_mean": float(boundary.mean() * ANNUALIZATION),
        "interior_annualized_mean": float(interior.mean() * ANNUALIZATION),
        "confidence_interval": {
            "lower": float(lower),
            "upper": float(upper),
        },
        "probability_mean_positive": float(np.mean(distribution > 0.0)),
        "passes": bool(lower > 0.0),
    }


def build_result(artifact_dir: Path) -> dict[str, Any]:
    market_results: dict[str, Any] = {}
    for market, metadata in MARKETS.items():
        market_dir = artifact_dir / market
        report = validate_report(
            market_dir / "walk_forward.json",
            metadata["report_sha256"],
        )
        frame = validate_returns(
            market_dir / "walk_forward_returns.csv",
            metadata["returns_sha256"],
        )
        validate_report_alignment(frame, report)
        market_results[market] = analyze_market(frame, seed=metadata["seed"])

    failures = [
        f"{market} fold-interior annualized mean lower confidence bound is not positive"
        for market, result in market_results.items()
        if not result["passes"]
    ]
    verdict = "improvement" if not failures else "rejected"
    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "Net rolling OOS strategy returns retain a positive annualized arithmetic mean in "
            "both BTC-USDT and ETH-USDT after excluding the first observation of every fold."
        ),
        "economic_rationale": (
            "A credible return process should persist inside each OOS fold rather than depend on "
            "the one-day parameter-reselection boundary where position carry and transaction-cost "
            "accounting are most implementation-sensitive."
        ),
        "candidate_accounting": {
            "candidate_count": CANDIDATE_COUNT,
            "candidates_passed": 1 if verdict == "improvement" else 0,
            "candidates_rejected": 0 if verdict == "improvement" else 1,
            "searched_alternatives": [],
        },
        "specification": {
            "annualization": ANNUALIZATION,
            "fold_count": FOLD_COUNT,
            "test_bars_per_fold": TEST_BARS,
            "excluded_observations_per_fold": EXCLUDED_OBSERVATIONS_PER_FOLD,
            "resampling": "within-fold non-circular moving blocks",
            "block_length": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "pass_rule": (
                "both market-specific confidence-interval lower bounds must be greater than zero"
            ),
        },
        "markets": market_results,
        "verdict": verdict,
        "failure_reasons": failures,
        "data_provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "markets": list(MARKETS),
            "source_workflow_run_id": 29886881484,
            "source_artifact_id": 8516824262,
            "source_artifact_name": "quant-research-484",
            "source_artifact_sha256": (
                "b1f271e4267cc1c1007bbccd11c53c1a59d3f1e3fe3f1e3f07423c6907b83605"
            ),
            "source_head_sha": "cfc0a08048ac584a375f15e4ed146c00266e2e17",
            "source_base_sha": "a57edb6838271e1ee86f901575cd13bcba895b9a",
            "returns_sha256": {
                market: metadata["returns_sha256"] for market, metadata in MARKETS.items()
            },
            "report_sha256": {
                market: metadata["report_sha256"] for market, metadata in MARKETS.items()
            },
            "evaluation_start": "2020-01-11T00:00:00+00:00",
            "evaluation_end": "2026-06-07T00:00:00+00:00",
            "observations_per_market": FOLD_COUNT * TEST_BARS,
            "development_evidence": True,
        },
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "The fixed one-observation exclusion tests only the immediate fold boundary.",
            "Resampling preserves within-fold serial order but does not model market impact, "
            "spread, liquidity, capacity, latency, or partial fills.",
            "Observed real returns are resampled; no artificial market-price path is generated.",
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test whether net OOS returns persist after excluding fold-boundary days."
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"candidate_count={result['candidate_accounting']['candidate_count']}")
    print(f"verdict={result['verdict']}")
    for market, market_result in result["markets"].items():
        interval = market_result["confidence_interval"]
        print(
            f"{market}: interior_mean={market_result['interior_annualized_mean']:.12f} "
            f"ci=[{interval['lower']:.12f},{interval['upper']:.12f}] "
            f"p_positive={market_result['probability_mean_positive']:.6f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
