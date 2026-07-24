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
VOLATILITY_LOOKBACK = 20
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
ANNUALIZATION = 365
ASSET_RETURN_COLUMN = "asset_return"
STRATEGY_RETURN_COLUMN = "strategy_return"
CANONICAL_SIGNATURE = (
    "lagged-volatility-regime-consistency-v1|markets=BTC-USDT,ETH-USDT|"
    "regime=median-of-prior-20d-realized-vol-recomputed-per-resample|"
    "prior-volatility=asset-return-shift1-rolling-std-ddof1|"
    "metric=annualized-arithmetic-mean-net-return|lookback=20|annualization=365|"
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
    required = {"timestamp", ASSET_RETURN_COLUMN, STRATEGY_RETURN_COLUMN}
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

    numeric = frame[[ASSET_RETURN_COLUMN, STRATEGY_RETURN_COLUMN]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    values = numeric.to_numpy(dtype=float)
    if numeric.isna().any().any() or not np.isfinite(values).all():
        raise ValueError("asset and strategy returns must be finite numbers")
    if np.any(numeric[ASSET_RETURN_COLUMN].to_numpy(dtype=float) <= -1.0):
        raise ValueError("asset returns must be greater than -1")
    if np.any(numeric[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float) <= -1.0):
        raise ValueError("strategy returns must be greater than -1")

    validated = frame.copy()
    validated["timestamp"] = parsed
    validated[[ASSET_RETURN_COLUMN, STRATEGY_RETURN_COLUMN]] = numeric
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


def lagged_realized_volatility(
    asset_returns: np.ndarray,
    lookback: int = VOLATILITY_LOOKBACK,
) -> np.ndarray:
    if asset_returns.ndim != 1 or len(asset_returns) <= lookback:
        raise ValueError("asset_returns must be one-dimensional and longer than lookback")
    if not np.isfinite(asset_returns).all() or np.any(asset_returns <= -1.0):
        raise ValueError("asset_returns must contain finite values greater than -1")
    if not isinstance(lookback, int) or isinstance(lookback, bool) or lookback < 2:
        raise ValueError("lookback must be an integer of at least 2")

    return (
        pd.Series(asset_returns)
        .shift(1)
        .rolling(lookback, min_periods=lookback)
        .std(ddof=1)
        .to_numpy(dtype=float)
    )


def regime_return_metrics(
    prior_volatility: np.ndarray,
    strategy_returns: np.ndarray,
    annualization: int = ANNUALIZATION,
) -> dict[str, float | int]:
    if prior_volatility.shape != strategy_returns.shape:
        raise ValueError("prior_volatility and strategy_returns must have identical shape")
    if prior_volatility.ndim != 1 or len(prior_volatility) < 2:
        raise ValueError("inputs must be non-empty one-dimensional arrays")
    if not np.isfinite(prior_volatility).all() or np.any(prior_volatility < 0.0):
        raise ValueError("prior_volatility must contain finite non-negative values")
    if not np.isfinite(strategy_returns).all() or np.any(strategy_returns <= -1.0):
        raise ValueError("strategy_returns must contain finite values greater than -1")
    if not isinstance(annualization, int) or isinstance(annualization, bool) or annualization <= 0:
        raise ValueError("annualization must be a positive integer")

    threshold = float(np.median(prior_volatility))
    low = prior_volatility <= threshold
    high = prior_volatility > threshold
    if not low.any() or not high.any():
        raise ValueError("volatility split must contain both low and high regimes")

    return {
        "high_vol_annualized_mean": float(np.mean(strategy_returns[high]) * annualization),
        "high_vol_observations": int(high.sum()),
        "low_vol_annualized_mean": float(np.mean(strategy_returns[low]) * annualization),
        "low_vol_observations": int(low.sum()),
        "prior_volatility_median": threshold,
    }


def analyze_market(frame: pd.DataFrame, seed: int) -> dict[str, object]:
    asset_returns = frame[ASSET_RETURN_COLUMN].to_numpy(dtype=float)
    strategy_returns = frame[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float)
    prior_volatility = lagged_realized_volatility(asset_returns)
    eligible = np.isfinite(prior_volatility)
    prior_volatility = prior_volatility[eligible]
    strategy_returns = strategy_returns[eligible]
    point = regime_return_metrics(prior_volatility, strategy_returns)

    low_means = np.empty(RESAMPLES, dtype=float)
    high_means = np.empty(RESAMPLES, dtype=float)
    rng = np.random.default_rng(seed)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(strategy_returns), BLOCK_LENGTH, rng)
        sampled = regime_return_metrics(prior_volatility[indices], strategy_returns[indices])
        low_means[sample_number] = float(sampled["low_vol_annualized_mean"])
        high_means[sample_number] = float(sampled["high_vol_annualized_mean"])

    alpha = 1.0 - CONFIDENCE

    def summarize(values: np.ndarray) -> dict[str, float | bool]:
        lower, median, upper = np.quantile(
            values,
            [alpha / 2.0, 0.5, 1.0 - alpha / 2.0],
        )
        return {
            "ci_lower": float(lower),
            "ci_upper": float(upper),
            "lower_bound_positive": bool(lower > 0.0),
            "median": float(median),
            "probability_positive": float(np.mean(values > 0.0)),
        }

    return {
        "bootstrap": {
            "high_vol": summarize(high_means),
            "low_vol": summarize(low_means),
        },
        "eligible_observations": len(strategy_returns),
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
        bool(result["bootstrap"][regime]["lower_bound_positive"])
        for result in market_results.values()
        for regime in ("low_vol", "high_vol")
    )
    failure_reasons = [
        f"{market} {regime.replace('_', '-')} lower confidence bound is not positive"
        for market, result in market_results.items()
        for regime in ("low_vol", "high_vol")
        if not bool(result["bootstrap"][regime]["lower_bound_positive"])
    ]
    return {
        "candidate_count": 1,
        "canonical_signature": CANONICAL_SIGNATURE,
        "claim_boundary": (
            "This is one predeclared regime diagnostic on BTC-USDT and ETH-USDT development "
            "markets. Regime labels use only the prior 20 observed asset returns. Arithmetic means "
            "on non-contiguous regime subsets are descriptive OOS evidence, not a tradable signal, "
            "causal claim, or untouched-holdout result."
        ),
        "failure_reasons": failure_reasons,
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, strategy net returns have a positive annualized "
            "arithmetic mean in both low- and high-volatility regimes, with every 95% paired "
            "moving-block-bootstrap lower bound above zero."
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
            "source_tested_commit": "fd8d2191e30bb0aeb80da0021f2923f3bc9a8377",
            "source_workflow_run_id": 29877892427,
        },
        "settings": {
            "annualization": ANNUALIZATION,
            "block_length": BLOCK_LENGTH,
            "candidate_count": 1,
            "confidence": CONFIDENCE,
            "development_market_screen": True,
            "markets": list(MARKETS),
            "primary_metric": "annualized_arithmetic_mean_net_return_by_regime",
            "prior_volatility": "asset_return.shift(1).rolling(20).std(ddof=1)",
            "regime_threshold": "median recomputed within every resample",
            "resamples": RESAMPLES,
            "resampling": "paired moving block bootstrap without circular wrapping",
            "seed_rule": "20260722 for BTC-USDT and 20260723 for ETH-USDT",
            "volatility_lookback": VOLATILITY_LOOKBACK,
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
