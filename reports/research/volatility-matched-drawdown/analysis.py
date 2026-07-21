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
    "volatility-matched-drawdown-v1|markets=BTC-USDT,ETH-USDT|"
    "benchmark=volatility-targeted-long|metric=max-drawdown-reduction|"
    "scale=recomputed-per-resample|block=20|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=0"
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
    if returns.isna().any().any() or not np.isfinite(returns.to_numpy(dtype=float)).all():
        raise ValueError("return columns must contain only finite numeric values")
    if (returns <= -1.0).any().any():
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


def maximum_drawdown(returns: np.ndarray) -> float:
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    running_peak = np.maximum.accumulate(nav)
    return float((nav / running_peak - 1.0).min())


def volatility_matched_statistics(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> dict[str, float]:
    strategy_volatility = float(np.std(strategy_returns, ddof=0))
    benchmark_volatility = float(np.std(benchmark_returns, ddof=0))
    if strategy_volatility <= 0.0:
        raise ValueError("strategy volatility must be positive")

    scale = benchmark_volatility / strategy_volatility
    scaled_strategy_drawdown = maximum_drawdown(strategy_returns * scale)
    benchmark_drawdown = maximum_drawdown(benchmark_returns)
    return {
        "scale": scale,
        "strategy_vol": strategy_volatility,
        "benchmark_vol": benchmark_volatility,
        "scaled_strategy_mdd": scaled_strategy_drawdown,
        "benchmark_mdd": benchmark_drawdown,
        "drawdown_reduction": abs(benchmark_drawdown) - abs(scaled_strategy_drawdown),
    }


def analyze_market(frame: pd.DataFrame, seed: int) -> dict[str, object]:
    strategy_returns = frame[STRATEGY_COLUMN].to_numpy(dtype=float)
    benchmark_returns = frame[BENCHMARK_COLUMN].to_numpy(dtype=float)
    point = volatility_matched_statistics(strategy_returns, benchmark_returns)

    rng = np.random.default_rng(seed)
    drawdown_reductions = np.empty(RESAMPLES, dtype=float)
    scales = np.empty(RESAMPLES, dtype=float)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(frame), BLOCK_LENGTH, rng)
        sample = volatility_matched_statistics(
            strategy_returns[indices], benchmark_returns[indices]
        )
        drawdown_reductions[sample_number] = sample["drawdown_reduction"]
        scales[sample_number] = sample["scale"]

    alpha = 1.0 - CONFIDENCE
    lower, median, upper = np.quantile(drawdown_reductions, [alpha / 2.0, 0.5, 1.0 - alpha / 2.0])
    scale_lower, scale_median, scale_upper = np.quantile(
        scales, [alpha / 2.0, 0.5, 1.0 - alpha / 2.0]
    )
    return {
        "observations": len(frame),
        "start": str(frame["timestamp"].iloc[0]),
        "end": str(frame["timestamp"].iloc[-1]),
        "point": point,
        "bootstrap": {
            "ci_lower": float(lower),
            "median": float(median),
            "ci_upper": float(upper),
            "probability_positive": float(np.mean(drawdown_reductions > 0.0)),
            "lower_bound_positive": bool(lower > 0.0),
            "scale_ci_lower": float(scale_lower),
            "scale_median": float(scale_median),
            "scale_ci_upper": float(scale_upper),
        },
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
        "candidate_count": 0,
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "After matching strategy daily volatility to the volatility-targeted-long "
            "benchmark within each paired moving-block sample, maximum drawdown reduction "
            "remains positive with a 95% lower confidence bound above zero for both "
            "BTC-USDT and ETH-USDT."
        ),
        "interpretation": {
            "BTC-USDT": (
                "The point estimate remains positive after volatility matching, but the "
                "95% interval crosses zero."
            ),
            "ETH-USDT": (
                "The point estimate remains positive on the original sequence, but the "
                "bootstrap median is negative and the 95% interval crosses zero."
            ),
            "claim_boundary": (
                "The existing lower-drawdown evidence cannot be distinguished from a "
                "lower-realized-volatility explanation under this fixed diagnostic. This "
                "is not evidence of alpha, superior Sharpe, deployable leverage, or a "
                "tradable sizing rule."
            ),
        },
        "joint_supported": joint_supported,
        "markets": market_results,
        "provenance": {
            "bar": "1Dutc",
            "instrument_type": "spot",
            "provider": "OKX",
            "source_artifact_id": 8499721759,
            "source_artifact_name": "quant-research-51",
            "source_artifact_sha256": (
                "dbe25282321fa1d1fdafa2945c1a45e6a6481060d693956fd5fb3225b03f3fd7"
            ),
            "source_head_sha": "4c02eccac3d6d81139c73d0b64bb5067756dac93",
            "source_workflow_run_id": 29841895366,
        },
        "settings": {
            "benchmark_column": BENCHMARK_COLUMN,
            "block_length": BLOCK_LENGTH,
            "confidence": CONFIDENCE,
            "market_status": "development",
            "markets": list(MARKETS),
            "metric": (
                "absolute benchmark maximum drawdown minus absolute volatility-matched "
                "strategy maximum drawdown"
            ),
            "resamples": RESAMPLES,
            "resampling": "paired moving block bootstrap without circular wrapping",
            "scale_definition": (
                "benchmark population standard deviation divided by strategy population "
                "standard deviation"
            ),
            "scale_recomputed_per_resample": True,
            "seed_rule": "20260722 for BTC-USDT; 20260723 for ETH-USDT",
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
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
