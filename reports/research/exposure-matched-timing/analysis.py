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
        "report_sha256": "78b0f635114bad273054167ed7d552c32e707c019cd28fde04a268a131765a3f",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "dd2d2d870f302f893a752f8db9b1d5cdfdca41f39e824fa6299d5d95eab04b76",
    },
}
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
ANNUALIZATION = 365
TRANSACTION_COST_BPS = 10.0
STRATEGY_COLUMN = "strategy_return"
ASSET_COLUMN = "asset_return"
POSITION_COLUMN = "position"
CANONICAL_SIGNATURE = (
    "exposure-matched-timing-v1|markets=BTC-USDT,ETH-USDT|"
    "benchmark=ex-post-constant-exposure-buy-and-hold|"
    "exposure=mean-executed-oos-position|"
    "metric=annualized-arithmetic-mean-net-return-delta|"
    "entry-cost=10bps-pro-rata|block=20|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:20260722,ETH-USDT:20260723|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_report(path: Path, expected_sha256: str) -> dict[str, object]:
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
        "max_abs_position": 1.0,
        "min_position": 0.0,
        "non_overlapping_test_folds": True,
        "selection_bars": 730,
        "test_bars": 90,
        "transaction_cost_bps": TRANSACTION_COST_BPS,
    }
    observed_settings = {
        "annualization": base_config.get("annualization"),
        "candidate_count": settings.get("candidate_count"),
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
    return report


def validate_returns(path: Path, expected_sha256: str) -> pd.DataFrame:
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"returns hash mismatch for {path}: expected {expected_sha256}, got {actual_sha256}"
        )

    frame = pd.read_csv(path)
    required = {"timestamp", STRATEGY_COLUMN, ASSET_COLUMN, POSITION_COLUMN}
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

    numeric = frame[[STRATEGY_COLUMN, ASSET_COLUMN, POSITION_COLUMN]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    values = numeric.to_numpy(dtype=float)
    if numeric.isna().any().any() or not np.isfinite(values).all():
        raise ValueError("strategy returns, asset returns, and positions must be finite numbers")
    returns = numeric[[STRATEGY_COLUMN, ASSET_COLUMN]].to_numpy(dtype=float)
    if np.any(returns <= -1.0):
        raise ValueError("returns must be greater than -1")
    positions = numeric[POSITION_COLUMN].to_numpy(dtype=float)
    if np.any((positions < 0.0) | (positions > 1.0)):
        raise ValueError("positions must stay within the declared long/cash range [0, 1]")

    validated = frame.copy()
    validated["timestamp"] = parsed
    validated[[STRATEGY_COLUMN, ASSET_COLUMN, POSITION_COLUMN]] = numeric
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


def constant_exposure_returns(
    asset_returns: np.ndarray,
    exposure: float,
    transaction_cost_bps: float,
) -> np.ndarray:
    if asset_returns.ndim != 1 or len(asset_returns) == 0:
        raise ValueError("asset_returns must be a non-empty one-dimensional array")
    if not np.isfinite(asset_returns).all() or np.any(asset_returns <= -1.0):
        raise ValueError("asset_returns must contain finite values greater than -1")
    if not math.isfinite(exposure) or not 0.0 <= exposure <= 1.0:
        raise ValueError("exposure must be finite and within [0, 1]")
    if not math.isfinite(transaction_cost_bps) or transaction_cost_bps < 0.0:
        raise ValueError("transaction_cost_bps must be finite and non-negative")

    returns = exposure * asset_returns.astype(float, copy=True)
    returns[0] -= exposure * transaction_cost_bps / 10_000.0
    return returns


def annualized_mean_return_delta(
    strategy_returns: np.ndarray,
    asset_returns: np.ndarray,
    exposure: float,
    transaction_cost_bps: float,
) -> float:
    if strategy_returns.shape != asset_returns.shape:
        raise ValueError("strategy_returns and asset_returns must have identical shape")
    if strategy_returns.ndim != 1 or len(strategy_returns) == 0:
        raise ValueError("strategy_returns must be a non-empty one-dimensional array")
    if not np.isfinite(strategy_returns).all() or np.any(strategy_returns <= -1.0):
        raise ValueError("strategy_returns must contain finite values greater than -1")

    matched_returns = constant_exposure_returns(
        asset_returns,
        exposure,
        transaction_cost_bps,
    )
    return float(np.mean(strategy_returns - matched_returns) * ANNUALIZATION)


def exposure_matched_metrics(
    strategy_returns: np.ndarray,
    asset_returns: np.ndarray,
    positions: np.ndarray,
    transaction_cost_bps: float,
) -> dict[str, float]:
    if strategy_returns.shape != asset_returns.shape or strategy_returns.shape != positions.shape:
        raise ValueError("strategy returns, asset returns, and positions must have identical shape")
    if positions.ndim != 1 or len(positions) == 0:
        raise ValueError("positions must be a non-empty one-dimensional array")
    if not np.isfinite(positions).all() or np.any((positions < 0.0) | (positions > 1.0)):
        raise ValueError("positions must be finite and within [0, 1]")

    exposure = float(np.mean(positions))
    matched_returns = constant_exposure_returns(
        asset_returns,
        exposure,
        transaction_cost_bps,
    )
    return {
        "annualized_mean_matched_return": float(np.mean(matched_returns) * ANNUALIZATION),
        "annualized_mean_return_delta": annualized_mean_return_delta(
            strategy_returns,
            asset_returns,
            exposure,
            transaction_cost_bps,
        ),
        "annualized_mean_strategy_return": float(np.mean(strategy_returns) * ANNUALIZATION),
        "average_executed_exposure": exposure,
        "matched_total_return": float(np.prod(1.0 + matched_returns) - 1.0),
        "strategy_total_return": float(np.prod(1.0 + strategy_returns) - 1.0),
    }


def analyze_market(frame: pd.DataFrame, seed: int) -> dict[str, object]:
    strategy_returns = frame[STRATEGY_COLUMN].to_numpy(dtype=float)
    asset_returns = frame[ASSET_COLUMN].to_numpy(dtype=float)
    positions = frame[POSITION_COLUMN].to_numpy(dtype=float)
    point = exposure_matched_metrics(
        strategy_returns,
        asset_returns,
        positions,
        TRANSACTION_COST_BPS,
    )
    exposure = float(point["average_executed_exposure"])

    deltas = np.empty(RESAMPLES, dtype=float)
    rng = np.random.default_rng(seed)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(strategy_returns), BLOCK_LENGTH, rng)
        deltas[sample_number] = annualized_mean_return_delta(
            strategy_returns[indices],
            asset_returns[indices],
            exposure,
            TRANSACTION_COST_BPS,
        )

    alpha = 1.0 - CONFIDENCE
    lower, median, upper = np.quantile(
        deltas,
        [alpha / 2.0, 0.5, 1.0 - alpha / 2.0],
    )
    return {
        "bootstrap": {
            "ci_lower": float(lower),
            "ci_upper": float(upper),
            "lower_bound_positive": bool(lower > 0.0),
            "median": float(median),
            "probability_positive": float(np.mean(deltas > 0.0)),
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
        bool(result["bootstrap"]["lower_bound_positive"]) for result in market_results.values()
    )
    return {
        "candidate_count": 1,
        "canonical_signature": CANONICAL_SIGNATURE,
        "claim_boundary": (
            "This is one predeclared exploratory mechanism diagnostic on BTC-USDT and ETH-USDT "
            "development markets. The exposure-matched benchmark is constructed ex post and is "
            "not an independently deployable or untouched-holdout strategy."
        ),
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, the strategy has a positive annualized arithmetic "
            "mean net-return delta versus a constant-exposure buy-and-hold benchmark whose "
            "exposure equals the strategy's average executed OOS position, with a positive 95% "
            "paired moving-block-bootstrap lower bound."
        ),
        "joint_supported": joint_supported,
        "markets": market_results,
        "provenance": {
            "bar": "1Dutc",
            "instrument_type": "spot",
            "provider": "OKX",
            "source_artifact_id": 8510950190,
            "source_artifact_name": "quant-research-328",
            "source_artifact_sha256": (
                "d997b795dffcb255c919f972d3364d2d8492b3bdd58f6e8ad7733f6ea5b0517a"
            ),
            "source_base_commit": "5a76277db73c156f248d276f8722f18ad18eef57",
            "source_persistent_head": "0e55db97fa397b2a1bc5aec63e19403251ced926",
            "source_tested_commit": "d74842a43ff4b4eab3906a0dd2b09417378bec10",
            "source_workflow_run_id": 29870506091,
        },
        "settings": {
            "annualization": ANNUALIZATION,
            "benchmark": "ex-post constant-exposure buy-and-hold",
            "block_length": BLOCK_LENGTH,
            "candidate_count": 1,
            "confidence": CONFIDENCE,
            "development_market_screen": True,
            "entry_cost_treatment": (
                "one pro-rata 10 bps entry charge at the first observation of the original or "
                "resampled benchmark path"
            ),
            "exposure_definition": "arithmetic mean of persisted executed OOS position",
            "markets": list(MARKETS),
            "primary_metric": "annualized_arithmetic_mean_net_return_delta",
            "resamples": RESAMPLES,
            "resampling": "paired moving block bootstrap without circular wrapping",
            "seed_rule": "20260722 for BTC-USDT and 20260723 for ETH-USDT",
            "transaction_cost_bps": TRANSACTION_COST_BPS,
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
