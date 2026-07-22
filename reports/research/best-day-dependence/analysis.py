from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

MARKETS = {
    "BTC-USDT": {
        "seed": 20260722,
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "c5262c4c8c0945b43907f006ca5bf986229c350e5e908d8baa4837cc2de32921",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "383d8273cdb12d8b3bfe271b4044eaa664c06018f7f6174f7a52f1ac1fdcdf24",
    },
}
BEST_RETURN_FRACTION = 0.01
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
ANNUALIZATION = 365
STRATEGY_RETURN_COLUMN = "strategy_return"
CANONICAL_SIGNATURE = (
    "best-day-dependence-v1|markets=BTC-USDT,ETH-USDT|"
    "stress=remove-ceil-top-1pct-strategy-returns-per-sample|"
    "metric=annualized-arithmetic-mean-net-return|annualization=365|"
    "block=20|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_report(path: Path, expected_sha256: str) -> None:
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"walk-forward report hash mismatch for {path}: "
            f"expected {expected_sha256}, got {actual_sha256}"
        )

    report = json.loads(path.read_text(encoding="utf-8"))
    settings = report.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("walk-forward report must contain settings")
    base_config = settings.get("base_config")
    if not isinstance(base_config, dict):
        raise ValueError("walk-forward report must contain settings.base_config")

    expected_settings = {
        "annualization": ANNUALIZATION,
        "candidate_count": 27,
        "cost_multipliers": [1.0, 2.0, 4.0],
        "max_abs_position": 1.0,
        "min_position": 0.0,
        "non_overlapping_test_folds": True,
        "selection_bars": 730,
        "test_bars": 90,
        "transaction_cost_bps": 10.0,
    }
    observed_settings = {
        "annualization": base_config.get("annualization"),
        "candidate_count": settings.get("candidate_count"),
        "cost_multipliers": settings.get("cost_multipliers"),
        "max_abs_position": base_config.get("max_abs_position"),
        "min_position": base_config.get("min_position"),
        "non_overlapping_test_folds": settings.get("non_overlapping_test_folds"),
        "selection_bars": settings.get("selection_bars"),
        "test_bars": settings.get("test_bars"),
        "transaction_cost_bps": base_config.get("transaction_cost_bps"),
    }
    if observed_settings != expected_settings:
        raise ValueError(
            "walk-forward settings do not match the predeclared research specification: "
            f"expected {expected_settings}, got {observed_settings}"
        )


def validate_returns(path: Path, expected_sha256: str) -> pd.DataFrame:
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"returns hash mismatch for {path}: expected {expected_sha256}, got {actual_sha256}"
        )

    frame = pd.read_csv(path)
    required = {"timestamp", STRATEGY_RETURN_COLUMN}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    timestamps: list[pd.Timestamp] = []
    for value in frame["timestamp"]:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamps must contain explicit timezone information")
        timestamps.append(timestamp)
    parsed = pd.Series(pd.to_datetime(timestamps, utc=True), index=frame.index)
    if parsed.duplicated().any() or not parsed.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(parsed) > 1 and not parsed.diff().iloc[1:].eq(pd.Timedelta(days=1)).all():
        raise ValueError("timestamps must have exact daily cadence")

    numeric = pd.to_numeric(frame[STRATEGY_RETURN_COLUMN], errors="coerce")
    values = numeric.to_numpy(dtype=float)
    if numeric.isna().any() or not np.isfinite(values).all():
        raise ValueError("strategy returns must be finite numbers")
    if np.any(values <= -1.0):
        raise ValueError("strategy returns must be greater than -1")

    validated = frame.copy()
    validated["timestamp"] = parsed
    validated[STRATEGY_RETURN_COLUMN] = numeric
    return validated


def moving_block_indices(
    observations: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if observations < block_length:
        raise ValueError("observations must be at least block_length")
    blocks_needed = math.ceil(observations / block_length)
    latest_start = observations - block_length
    starts = rng.integers(0, latest_start + 1, size=blocks_needed)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observations]


def best_day_stress_metrics(
    strategy_returns: np.ndarray,
    best_return_fraction: float = BEST_RETURN_FRACTION,
    annualization: int = ANNUALIZATION,
) -> dict[str, float | int]:
    if strategy_returns.ndim != 1 or len(strategy_returns) < 3:
        raise ValueError("strategy_returns must be a one-dimensional array with at least 3 values")
    if not np.isfinite(strategy_returns).all() or np.any(strategy_returns <= -1.0):
        raise ValueError("strategy_returns must contain finite values greater than -1")
    if not math.isfinite(best_return_fraction) or not 0.0 < best_return_fraction < 1.0:
        raise ValueError("best_return_fraction must be finite and strictly between 0 and 1")
    if not isinstance(annualization, int) or isinstance(annualization, bool) or annualization <= 0:
        raise ValueError("annualization must be a positive integer")

    removed_observations = math.ceil(len(strategy_returns) * best_return_fraction)
    retained_observations = len(strategy_returns) - removed_observations
    if retained_observations < 2:
        raise ValueError("best-day stress must retain at least two observations")

    ordered = np.sort(strategy_returns, kind="stable")
    retained = ordered[:retained_observations]
    removed = ordered[retained_observations:]
    return {
        "annualized_mean_after_stress": float(np.mean(retained) * annualization),
        "annualized_mean_before_stress": float(np.mean(strategy_returns) * annualization),
        "largest_removed_return": float(removed[-1]),
        "removed_observations": removed_observations,
        "retained_observations": retained_observations,
        "smallest_removed_return": float(removed[0]),
        "stress_delta": float((np.mean(strategy_returns) - np.mean(retained)) * annualization),
    }


def analyze_market(frame: pd.DataFrame, seed: int) -> dict[str, object]:
    strategy_returns = frame[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float)
    point = best_day_stress_metrics(strategy_returns)

    stressed_means = np.empty(RESAMPLES, dtype=float)
    rng = np.random.default_rng(seed)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(strategy_returns), BLOCK_LENGTH, rng)
        sampled = best_day_stress_metrics(strategy_returns[indices])
        stressed_means[sample_number] = float(sampled["annualized_mean_after_stress"])

    alpha = 1.0 - CONFIDENCE
    lower, median, upper = np.quantile(
        stressed_means,
        [alpha / 2.0, 0.5, 1.0 - alpha / 2.0],
    )
    return {
        "bootstrap": {
            "ci_lower": float(lower),
            "ci_upper": float(upper),
            "lower_bound_positive": bool(lower > 0.0),
            "median": float(median),
            "probability_positive": float(np.mean(stressed_means > 0.0)),
        },
        "end": str(frame["timestamp"].iloc[-1]),
        "observations": len(frame),
        "point": point,
        "start": str(frame["timestamp"].iloc[0]),
    }


def build_result(artifact_dir: Path) -> dict[str, object]:
    market_results: dict[str, dict[str, object]] = {}
    for market, metadata in MARKETS.items():
        market_dir = artifact_dir / market
        report_path = market_dir / "walk_forward.json"
        returns_path = market_dir / "walk_forward_returns.csv"
        validate_report(report_path, str(metadata["report_sha256"]))
        frame = validate_returns(returns_path, str(metadata["returns_sha256"]))
        result = analyze_market(frame, int(metadata["seed"]))
        result["report_sha256"] = str(metadata["report_sha256"])
        result["returns_sha256"] = str(metadata["returns_sha256"])
        market_results[market] = result

    joint_supported = all(
        bool(result["bootstrap"]["lower_bound_positive"])
        for result in market_results.values()
    )
    failure_reasons = [
        f"{market} stressed-mean lower confidence bound is not positive"
        for market, result in market_results.items()
        if not bool(result["bootstrap"]["lower_bound_positive"])
    ]
    return {
        "candidate_count": 1,
        "canonical_signature": CANONICAL_SIGNATURE,
        "claim_boundary": (
            "This is one predeclared outlier-dependence stress on BTC-USDT and ETH-USDT "
            "development markets. Removing best observations is an ex-post diagnostic, not a "
            "tradable rule, causal claim, untouched-holdout result, or execution model."
        ),
        "failure_reasons": failure_reasons,
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, net OOS strategy returns retain a positive "
            "annualized arithmetic mean after removing exactly the largest 1% of strategy-return "
            "observations, with each 95% moving-block-bootstrap lower bound above zero."
        ),
        "joint_supported": joint_supported,
        "markets": market_results,
        "provenance": {
            "bar": "1Dutc",
            "instrument_type": "spot",
            "provider": "OKX",
            "source_artifact_id": 8513672060,
            "source_artifact_name": "quant-research-378",
            "source_artifact_sha256": (
                "7902fd0e653a446151188dc426386bfb8406d404a348aaf8be13a7671deb10ec"
            ),
            "source_base_commit": "a2f1ab460409113057198ebdd00e3ce4f6c7bf82",
            "source_persistent_head": "e1f49e3ad33fa2cd820de5ca0a6f70231f214a20",
            "source_tested_merge_commit": "fd8d2191e30bb0aeb80da0021f2923f3bc9a8377",
            "source_workflow_run_id": 29877892427,
        },
        "settings": {
            "annualization": ANNUALIZATION,
            "best_return_fraction": BEST_RETURN_FRACTION,
            "block_length": BLOCK_LENGTH,
            "candidate_count": 1,
            "confidence": CONFIDENCE,
            "development_market_screen": True,
            "removal_count_rule": "ceil(observations * best_return_fraction)",
            "resamples": RESAMPLES,
        },
        "verdict": "supported" if joint_supported else "rejected",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test dependence on the best 1% of OOS days")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        required=True,
        help="Directory containing BTC-USDT and ETH-USDT workflow-artifact folders",
    )
    parser.add_argument("--output", type=Path, required=True, help="Result JSON path")
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
