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
        "seeds": {"first_half": 20260722, "second_half": 20260724},
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "c5262c4c8c0945b43907f006ca5bf986229c350e5e908d8baa4837cc2de32921",
    },
    "ETH-USDT": {
        "seeds": {"first_half": 20260723, "second_half": 20260725},
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "383d8273cdb12d8b3bfe271b4044eaa664c06018f7f6174f7a52f1ac1fdcdf24",
    },
}
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
ANNUALIZATION = 365
STRATEGY_RETURN_COLUMN = "strategy_return"
CANONICAL_SIGNATURE = (
    "chronological-half-return-consistency-v1|markets=BTC-USDT,ETH-USDT|"
    "split=equal-observation-halves-first1170-second1170|"
    "metric=annualized-arithmetic-mean-net-return|annualization=365|"
    "block=20|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:first:20260722,second:20260724;"
    "ETH-USDT:first:20260723,second:20260725|candidate_count=1"
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


def chronological_halves(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if values.ndim != 1 or len(values) < 2:
        raise ValueError("values must be a one-dimensional array with at least two observations")
    if len(values) % 2:
        raise ValueError("equal chronological halves require an even observation count")
    if not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("values must contain finite returns greater than -1")

    midpoint = len(values) // 2
    return values[:midpoint].copy(), values[midpoint:].copy()


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


def analyze_half(values: np.ndarray, seed: int) -> dict[str, object]:
    point = float(np.mean(values) * ANNUALIZATION)
    means = np.empty(RESAMPLES, dtype=float)
    rng = np.random.default_rng(seed)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(values), BLOCK_LENGTH, rng)
        means[sample_number] = float(np.mean(values[indices]) * ANNUALIZATION)

    alpha = 1.0 - CONFIDENCE
    lower, median, upper = np.quantile(
        means,
        [alpha / 2.0, 0.5, 1.0 - alpha / 2.0],
    )
    return {
        "annualized_mean": point,
        "bootstrap": {
            "ci_lower": float(lower),
            "ci_upper": float(upper),
            "lower_bound_positive": bool(lower > 0.0),
            "median": float(median),
            "probability_positive": float(np.mean(means > 0.0)),
        },
        "observations": len(values),
        "seed": seed,
    }


def analyze_market(frame: pd.DataFrame, seeds: dict[str, int]) -> dict[str, object]:
    values = frame[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float)
    first_values, second_values = chronological_halves(values)
    midpoint = len(first_values)

    first_result = analyze_half(first_values, seeds["first_half"])
    first_result.update(
        {
            "end": str(frame["timestamp"].iloc[midpoint - 1]),
            "start": str(frame["timestamp"].iloc[0]),
        }
    )
    second_result = analyze_half(second_values, seeds["second_half"])
    second_result.update(
        {
            "end": str(frame["timestamp"].iloc[-1]),
            "start": str(frame["timestamp"].iloc[midpoint]),
        }
    )
    return {
        "full_observations": len(frame),
        "halves": {
            "first_half": first_result,
            "second_half": second_result,
        },
        "split_index": midpoint,
        "split_rule": "first n/2 observations versus final n/2 observations",
    }


def build_result(artifact_dir: Path) -> dict[str, object]:
    market_results: dict[str, dict[str, object]] = {}
    for market, metadata in MARKETS.items():
        market_dir = artifact_dir / market
        report_path = market_dir / "walk_forward.json"
        returns_path = market_dir / "walk_forward_returns.csv"
        validate_report(report_path, str(metadata["report_sha256"]))
        frame = validate_returns(returns_path, str(metadata["returns_sha256"]))
        result = analyze_market(frame, dict(metadata["seeds"]))
        result["report_sha256"] = str(metadata["report_sha256"])
        result["returns_sha256"] = str(metadata["returns_sha256"])
        market_results[market] = result

    joint_supported = all(
        bool(half_result["bootstrap"]["lower_bound_positive"])
        for market_result in market_results.values()
        for half_result in market_result["halves"].values()
    )
    failure_reasons = [
        f"{market} {half_name.replace('_', ' ')} mean lower confidence bound is not positive"
        for market, market_result in market_results.items()
        for half_name, half_result in market_result["halves"].items()
        if not bool(half_result["bootstrap"]["lower_bound_positive"])
    ]
    return {
        "candidate_count": 1,
        "canonical_signature": CANONICAL_SIGNATURE,
        "claim_boundary": (
            "This is one predeclared temporal-stability diagnostic on BTC-USDT and ETH-USDT "
            "development markets. The midpoint is fixed by observation count and is not a new "
            "holdout, tradable switching rule, causal claim, or execution model."
        ),
        "failure_reasons": failure_reasons,
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, net OOS strategy returns have a positive annualized "
            "arithmetic mean in both equal chronological halves, with all four 95% moving-block-"
            "bootstrap lower bounds above zero."
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
            "block_length": BLOCK_LENGTH,
            "candidate_count": 1,
            "confidence": CONFIDENCE,
            "development_market_screen": True,
            "resamples_per_half": RESAMPLES,
            "split_rule": "equal chronological halves by observation count",
        },
        "verdict": "supported" if joint_supported else "rejected",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test chronological half-sample return consistency"
    )
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
