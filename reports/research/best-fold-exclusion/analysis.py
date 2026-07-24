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
        "report_sha256": "e003da1dbedb57b87f8a596fd480f175c5d316fc7e9059ce8edfbe2c954fa88c",
        "seed": 20260723,
    },
    "ETH-USDT": {
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "bb30925eb8351218db08f28a63d32ab32a702fac7008297e90f8f7c3cf329f05",
        "seed": 20260724,
    },
}
ANNUALIZATION = 365
FOLD_COUNT = 26
TEST_BARS = 90
RESAMPLES = 2_000
CONFIDENCE = 0.95
CANDIDATE_COUNT = 1
CANONICAL_SIGNATURE = (
    "best-fold-exclusion-consistency-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|"
    "stress=remove-single-fold-with-highest-compounded-net-return-per-market|"
    "folds=26x90|metric=annualized-arithmetic-mean-net-return|annualization=365|"
    "resampling=remaining-folds-with-replacement-as-90bar-blocks|resamples=2000|"
    "confidence=0.95|seeds=BTC-USDT:20260723,ETH-USDT:20260724|candidate_count=1"
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
            "walk-forward settings do not match the predeclared best-fold exclusion test: "
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
    values = returns.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError("strategy_return must contain finite values")
    if np.any(values <= -1.0):
        raise ValueError("strategy_return must be greater than -1")
    fold_values = folds.to_numpy(dtype=float)
    if not np.equal(fold_values, fold_values.astype(int)).all():
        raise ValueError("fold identifiers must be integers")

    validated = pd.DataFrame(
        {
            "timestamp": timestamps,
            "fold": fold_values.astype(int),
            "strategy_return": values,
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
    for fold_report, (fold_id, fold_frame) in zip(
        report["folds"], frame.groupby("fold", sort=True), strict=True
    ):
        if fold_report["fold"] != fold_id:
            raise ValueError("report and returns fold identifiers do not align")
        if fold_frame["timestamp"].iloc[0].isoformat() != fold_report["test_start"]:
            raise ValueError(f"fold {fold_id} test_start does not align with returns")
        if fold_frame["timestamp"].iloc[-1].isoformat() != fold_report["test_end"]:
            raise ValueError(f"fold {fold_id} test_end does not align with returns")


def compounded_return(values: np.ndarray) -> float:
    if values.ndim != 1 or len(values) == 0:
        raise ValueError("returns must be a non-empty one-dimensional array")
    return float(np.prod(1.0 + values) - 1.0)


def exclude_best_fold(frame: pd.DataFrame) -> tuple[int, float, tuple[np.ndarray, ...]]:
    fold_data: list[tuple[int, float, np.ndarray]] = []
    for fold_id, fold_frame in frame.groupby("fold", sort=True):
        values = fold_frame["strategy_return"].to_numpy(dtype=float)
        fold_data.append((int(fold_id), compounded_return(values), values.copy()))
    if len(fold_data) < 2:
        raise ValueError("at least two folds are required")

    best_fold_id, best_fold_total_return, _ = max(
        fold_data,
        key=lambda item: (item[1], -item[0]),
    )
    remaining = tuple(values for fold_id, _, values in fold_data if fold_id != best_fold_id)
    if len(remaining) != len(fold_data) - 1:
        raise RuntimeError("exactly one best fold must be excluded")
    return best_fold_id, best_fold_total_return, remaining


def fold_block_mean_distribution(
    folds: Sequence[np.ndarray],
    *,
    resamples: int,
    annualization: int,
    seed: int,
) -> np.ndarray:
    if not folds or resamples < 1 or annualization < 2:
        raise ValueError("folds, resamples, and annualization must be valid")
    fold_length = len(folds[0])
    if fold_length == 0 or any(fold.ndim != 1 or len(fold) != fold_length for fold in folds):
        raise ValueError("all folds must be non-empty one-dimensional arrays of equal length")

    rng = np.random.default_rng(seed)
    fold_sums = np.asarray([float(fold.sum()) for fold in folds], dtype=float)
    distribution = np.empty(resamples, dtype=float)
    denominator = len(folds) * fold_length
    for resample_index in range(resamples):
        selected = rng.integers(0, len(folds), size=len(folds))
        distribution[resample_index] = (
            float(fold_sums[selected].sum()) / denominator * annualization
        )
    return distribution


def analyze_market(frame: pd.DataFrame, *, seed: int) -> dict[str, Any]:
    best_fold_id, best_fold_total_return, remaining_folds = exclude_best_fold(frame)
    remaining = np.concatenate(remaining_folds)
    full = frame["strategy_return"].to_numpy(dtype=float)
    distribution = fold_block_mean_distribution(
        remaining_folds,
        resamples=RESAMPLES,
        annualization=ANNUALIZATION,
        seed=seed,
    )
    alpha = 1.0 - CONFIDENCE
    lower, upper = np.quantile(distribution, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "seed": seed,
        "full_fold_count": FOLD_COUNT,
        "remaining_fold_count": len(remaining_folds),
        "full_observations": len(full),
        "remaining_observations": len(remaining),
        "excluded_best_fold": best_fold_id,
        "excluded_best_fold_total_return": best_fold_total_return,
        "full_annualized_mean": float(full.mean() * ANNUALIZATION),
        "remaining_annualized_mean": float(remaining.mean() * ANNUALIZATION),
        "confidence_interval": {"lower": float(lower), "upper": float(upper)},
        "probability_mean_positive": float(np.mean(distribution > 0.0)),
        "passes": bool(lower > 0.0),
    }


def build_result(artifact_dir: Path) -> dict[str, Any]:
    market_results: dict[str, Any] = {}
    for market, metadata in MARKETS.items():
        market_dir = artifact_dir / market
        report = validate_report(market_dir / "walk_forward.json", metadata["report_sha256"])
        frame = validate_returns(
            market_dir / "walk_forward_returns.csv",
            metadata["returns_sha256"],
        )
        validate_report_alignment(frame, report)
        market_results[market] = analyze_market(frame, seed=metadata["seed"])

    failures = [
        f"{market} best-fold-excluded annualized mean lower confidence bound is not positive"
        for market, result in market_results.items()
        if not result["passes"]
    ]
    verdict = "improvement" if not failures else "rejected"
    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "Net rolling OOS strategy returns retain a positive annualized arithmetic mean in "
            "both BTC-USDT and ETH-USDT after removing each market's single best fold."
        ),
        "economic_rationale": (
            "A credible adaptive process should not depend on one exceptional 90-session OOS fold. "
            "Removing the fold with the highest compounded net return directly stress-tests the "
            "profit-concentration failure reported by the canonical BTC research run."
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
            "excluded_folds_per_market": 1,
            "exclusion_rule": (
                "highest compounded net strategy return; earliest fold wins exact ties"
            ),
            "resampling": "remaining 90-session folds sampled with replacement as complete blocks",
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "pass_rule": "both market lower confidence bounds must be strictly positive",
        },
        "markets": market_results,
        "failure_reasons": failures,
        "verdict": verdict,
        "source": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29922259536,
            "source_artifact_id": 8530429665,
            "source_artifact_name": "quant-research-source-1027-attempt-1",
            "source_artifact_sha256": (
                "da7ab1b69654f50d0da42e2898a69780269e797bcc808dfdaf1f4e04ae9b64df"
            ),
            "source_code_commit": "a065d4f6c04e21e806e123abdb00a9315055645c",
            "evaluation_start": "2020-01-11T00:00:00+00:00",
            "evaluation_end": "2026-06-07T00:00:00+00:00",
            "development_markets": True,
            "return_file_sha256": {
                market: metadata["returns_sha256"] for market, metadata in MARKETS.items()
            },
            "report_file_sha256": {
                market: metadata["report_sha256"] for market, metadata in MARKETS.items()
            },
        },
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            (
                "The best fold is selected adversarially from the complete OOS path as a fixed "
                "stress, not as a deployable rule."
            ),
            (
                "Fold-block resampling preserves each 90-session path but treats remaining folds "
                "as exchangeable and does not preserve dependence across fold boundaries."
            ),
            (
                "Spread, market impact, liquidity, capacity, latency, and partial fills are not "
                "modeled beyond persisted transaction costs."
            ),
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the best-fold exclusion stress test.")
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"verdict={result['verdict']}")
    for market, market_result in result["markets"].items():
        print(
            f"{market}: excluded_fold={market_result['excluded_best_fold']} "
            f"remaining_mean={market_result['remaining_annualized_mean']:.12f} "
            f"lower={market_result['confidence_interval']['lower']:.12f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
