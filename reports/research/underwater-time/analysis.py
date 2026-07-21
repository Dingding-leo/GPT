from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Callable
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
    "underwater-time-v1|markets=BTC-USDT,ETH-USDT|"
    "benchmark=volatility-targeted-long|metric=underwater-fraction-reduction|"
    "definition=nav-below-prior-running-peak|block=20|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=4"
)

Metric = Callable[[np.ndarray], float]


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

    returns = frame[[STRATEGY_COLUMN, BENCHMARK_COLUMN]].apply(
        pd.to_numeric, errors="coerce"
    )
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


def drawdowns(returns: np.ndarray) -> np.ndarray:
    nav = np.cumprod(1.0 + returns)
    running_peak = np.maximum.accumulate(np.concatenate(([1.0], nav)))[1:]
    return nav / running_peak - 1.0


def underwater_fraction(returns: np.ndarray) -> float:
    return float(np.mean(drawdowns(returns) < -1e-12))


def mean_drawdown_depth(returns: np.ndarray) -> float:
    return float(np.mean(-drawdowns(returns)))


def ulcer_index(returns: np.ndarray) -> float:
    series = drawdowns(returns)
    return float(np.sqrt(np.mean(series * series)))


def maximum_underwater_duration(returns: np.ndarray) -> float:
    underwater = drawdowns(returns) < -1e-12
    current = 0
    longest = 0
    for value in underwater:
        current = current + 1 if value else 0
        longest = max(longest, current)
    return float(longest)


METRICS: dict[str, Metric] = {
    "underwater_fraction": underwater_fraction,
    "ulcer_index": ulcer_index,
    "mean_drawdown_depth": mean_drawdown_depth,
    "maximum_underwater_duration": maximum_underwater_duration,
}


def analyze_metric(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    metric: Metric,
    rng: np.random.Generator,
) -> dict[str, object]:
    strategy_value = metric(strategy_returns)
    benchmark_value = metric(benchmark_returns)
    reductions = np.empty(RESAMPLES, dtype=float)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(strategy_returns), BLOCK_LENGTH, rng)
        reductions[sample_number] = metric(benchmark_returns[indices]) - metric(
            strategy_returns[indices]
        )

    alpha = 1.0 - CONFIDENCE
    lower, median, upper = np.quantile(
        reductions, [alpha / 2.0, 0.5, 1.0 - alpha / 2.0]
    )
    return {
        "point": {
            "strategy": strategy_value,
            "benchmark": benchmark_value,
            "reduction": benchmark_value - strategy_value,
        },
        "bootstrap": {
            "ci_lower": float(lower),
            "median": float(median),
            "ci_upper": float(upper),
            "probability_positive": float(np.mean(reductions > 0.0)),
            "lower_bound_positive": bool(lower > 0.0),
        },
    }


def analyze_market(frame: pd.DataFrame, seed: int) -> dict[str, object]:
    strategy_returns = frame[STRATEGY_COLUMN].to_numpy(dtype=float)
    benchmark_returns = frame[BENCHMARK_COLUMN].to_numpy(dtype=float)
    metrics: dict[str, dict[str, object]] = {}
    for metric_index, (name, metric) in enumerate(METRICS.items()):
        metrics[name] = analyze_metric(
            strategy_returns,
            benchmark_returns,
            metric,
            np.random.default_rng(seed + metric_index * 10_000),
        )

    return {
        "observations": len(frame),
        "start": str(frame["timestamp"].iloc[0]),
        "end": str(frame["timestamp"].iloc[-1]),
        "metrics": metrics,
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
        bool(
            result["metrics"]["underwater_fraction"]["bootstrap"][
                "lower_bound_positive"
            ]
        )
        for result in market_results.values()
    )
    return {
        "candidate_count": len(METRICS),
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, the strategy spends a smaller fraction of "
            "out-of-sample days below its own prior running equity peak than the "
            "volatility-targeted-long benchmark, with a positive 95% paired "
            "moving-block-bootstrap lower bound for the reduction."
        ),
        "joint_supported": joint_supported,
        "markets": market_results,
        "metric_screen": {
            "maximum_underwater_duration": {
                "disposition": "not primary",
                "reason": (
                    "The longest-run statistic is discontinuous and highly unstable when "
                    "moving blocks are concatenated into new paths."
                ),
            },
            "mean_drawdown_depth": {
                "disposition": "not primary",
                "reason": (
                    "It mainly repeats the existing drawdown-depth evidence and does not "
                    "measure how frequently capital remains impaired."
                ),
            },
            "ulcer_index": {
                "disposition": "not primary",
                "reason": (
                    "It combines depth and time but remains dominated by the already-tested "
                    "drawdown-depth mechanism."
                ),
            },
            "underwater_fraction": {
                "disposition": "primary",
                "reason": (
                    "It is bounded, uses every OOS observation, and directly measures the "
                    "fraction of time capital remains below its previous peak."
                ),
            },
        },
        "provenance": {
            "bar": "1Dutc",
            "instrument_type": "spot",
            "provider": "OKX",
            "source_artifact_id": 8507019983,
            "source_artifact_name": "quant-research-246",
            "source_artifact_sha256": (
                "a3915a12b355c7eaed58c83c459c1d4e74f42c23815963cdab75d88fad17205a"
            ),
            "source_tested_commit": "196d925f9b3dedd3e6a6382304405952eb16a073",
            "source_workflow_run_id": 29860303180,
        },
        "settings": {
            "benchmark_column": BENCHMARK_COLUMN,
            "block_length": BLOCK_LENGTH,
            "confidence": CONFIDENCE,
            "development_market_screen": True,
            "markets": list(MARKETS),
            "primary_metric": "underwater_fraction",
            "primary_metric_definition": (
                "fraction of OOS observations whose compounded NAV is below the running "
                "maximum including initial capital"
            ),
            "resamples": RESAMPLES,
            "resampling": "paired moving block bootstrap without circular wrapping",
            "seed_rule": (
                "base seed 20260722 for BTC-USDT and 20260723 for ETH-USDT; each screened "
                "metric uses a deterministic 10000-step seed offset"
            ),
            "strategy_column": STRATEGY_COLUMN,
        },
        "verdict": "supported" if joint_supported else "rejected",
        "claim_boundary": (
            "This is an exploratory diagnostic on development markets after a four-metric "
            "screen, not untouched confirmatory evidence. It does not change the strategy, "
            "fees, execution delay, candidate grid, or sealed-market verdict."
        ),
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
