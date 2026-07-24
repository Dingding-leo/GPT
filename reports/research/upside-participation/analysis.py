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
    },
    "ETH-USDT": {
        "seed": 20260723,
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
    },
}
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
STRATEGY_COLUMN = "strategy_return"
BENCHMARK_COLUMN = "benchmark_volatility_targeted_long_return"
CANONICAL_SIGNATURE = (
    "upside-participation-asymmetry-v1|markets=BTC-USDT,ETH-USDT|"
    "benchmark=volatility-targeted-long|metric=upside-capture-minus-downside-capture|"
    "capture=conditional-arithmetic-mean-ratio|block=20|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_returns(path: Path, expected_sha256: str) -> pd.DataFrame:
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"returns hash mismatch for {path}: expected {expected_sha256}, got {actual_sha256}"
        )

    frame = pd.read_csv(path)
    required = {"timestamp", STRATEGY_COLUMN, BENCHMARK_COLUMN}
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

    returns = frame[[STRATEGY_COLUMN, BENCHMARK_COLUMN]].apply(pd.to_numeric, errors="coerce")
    values = returns.to_numpy(dtype=float)
    if returns.isna().any().any() or not np.isfinite(values).all():
        raise ValueError("return columns must contain only finite numeric values")
    if np.any(values <= -1.0):
        raise ValueError("returns must be greater than -1")

    validated = frame.copy()
    validated["timestamp"] = parsed
    return validated


def moving_block_indices(
    observations: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    blocks_needed = math.ceil(observations / block_length)
    latest_start = observations - block_length
    starts = rng.integers(0, latest_start + 1, size=blocks_needed)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observations]


def participation_capture(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> dict[str, float | int]:
    if strategy_returns.shape != benchmark_returns.shape:
        raise ValueError("strategy and benchmark returns must have identical shape")
    upside = benchmark_returns > 0.0
    downside = benchmark_returns < 0.0
    if not upside.any() or not downside.any():
        raise ValueError("benchmark must contain both positive and negative observations")

    benchmark_upside_mean = float(np.mean(benchmark_returns[upside]))
    benchmark_downside_mean = float(np.mean(benchmark_returns[downside]))
    if benchmark_upside_mean <= 0.0 or benchmark_downside_mean >= 0.0:
        raise ValueError("benchmark conditional means have invalid signs")

    upside_capture = float(np.mean(strategy_returns[upside]) / benchmark_upside_mean)
    downside_capture = float(np.mean(strategy_returns[downside]) / benchmark_downside_mean)
    return {
        "asymmetry": upside_capture - downside_capture,
        "downside_capture": downside_capture,
        "downside_observations": int(np.sum(downside)),
        "upside_capture": upside_capture,
        "upside_observations": int(np.sum(upside)),
        "zero_benchmark_observations": int(np.sum(benchmark_returns == 0.0)),
    }


def analyze_market(frame: pd.DataFrame, seed: int) -> dict[str, object]:
    strategy_returns = frame[STRATEGY_COLUMN].to_numpy(dtype=float)
    benchmark_returns = frame[BENCHMARK_COLUMN].to_numpy(dtype=float)
    point = participation_capture(strategy_returns, benchmark_returns)

    asymmetries = np.empty(RESAMPLES, dtype=float)
    rng = np.random.default_rng(seed)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(strategy_returns), BLOCK_LENGTH, rng)
        sample = participation_capture(strategy_returns[indices], benchmark_returns[indices])
        asymmetries[sample_number] = float(sample["asymmetry"])

    alpha = 1.0 - CONFIDENCE
    lower, median, upper = np.quantile(
        asymmetries,
        [alpha / 2.0, 0.5, 1.0 - alpha / 2.0],
    )
    return {
        "bootstrap": {
            "ci_lower": float(lower),
            "ci_upper": float(upper),
            "lower_bound_positive": bool(lower > 0.0),
            "median": float(median),
            "probability_positive": float(np.mean(asymmetries > 0.0)),
        },
        "end": str(frame["timestamp"].iloc[-1]),
        "observations": len(frame),
        "point": point,
        "start": str(frame["timestamp"].iloc[0]),
    }


def build_result(artifact_dir: Path) -> dict[str, object]:
    market_results: dict[str, dict[str, object]] = {}
    for market, metadata in MARKETS.items():
        returns_path = artifact_dir / market / "walk_forward_returns.csv"
        frame = validate_returns(returns_path, str(metadata["returns_sha256"]))
        result = analyze_market(frame, int(metadata["seed"]))
        result["sha256"] = str(metadata["returns_sha256"])
        market_results[market] = result

    joint_supported = all(
        bool(result["bootstrap"]["lower_bound_positive"]) for result in market_results.values()
    )
    return {
        "candidate_count": 1,
        "canonical_signature": CANONICAL_SIGNATURE,
        "claim_boundary": (
            "This is a single predeclared exploratory mechanism test on BTC-USDT and "
            "ETH-USDT development markets. It does not alter the strategy, candidate grid, "
            "fees, execution delay, split rules, or sealed-market verdict."
        ),
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, upside capture relative to the "
            "volatility-targeted-long benchmark exceeds downside capture, with a positive "
            "95% paired moving-block-bootstrap lower bound for the difference."
        ),
        "joint_supported": joint_supported,
        "markets": market_results,
        "provenance": {
            "bar": "1Dutc",
            "instrument_type": "spot",
            "provider": "OKX",
            "source_artifact_id": 8509324116,
            "source_artifact_name": "quant-research-306",
            "source_artifact_sha256": (
                "67e84186d26f3d5e1806d77be1c9ff3c4f9da8d041da12d63a40d00e79a42a4a"
            ),
            "source_persistent_head": "28d9911192806a045e27aef5512967ecb570d919",
            "source_tested_commit": "a48afc549121678fb066899db67fe20faf2f5b30",
            "source_workflow_run_id": 29866245582,
        },
        "settings": {
            "benchmark_column": BENCHMARK_COLUMN,
            "block_length": BLOCK_LENGTH,
            "candidate_count": 1,
            "capture_definition": (
                "conditional arithmetic mean strategy return divided by conditional arithmetic "
                "mean benchmark return, with conditioning determined by benchmark return sign"
            ),
            "confidence": CONFIDENCE,
            "development_market_screen": True,
            "markets": list(MARKETS),
            "primary_metric": "upside_capture_minus_downside_capture",
            "resamples": RESAMPLES,
            "resampling": "paired moving block bootstrap without circular wrapping",
            "seed_rule": "20260722 for BTC-USDT and 20260723 for ETH-USDT",
            "strategy_column": STRATEGY_COLUMN,
        },
        "verdict": "supported" if joint_supported else "rejected",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
