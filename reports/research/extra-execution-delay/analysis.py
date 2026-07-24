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
        "report_sha256": "eadade3fd883744d6bf9edeb798a0c8ca2bd62b621d936c70717a4e38e11fd9a",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "b2bf91d7ed00e016931ffe4d892827d769a44fb0dae8af58bc1d6785a0207067",
    },
}
ANNUALIZATION = 365
TRANSACTION_COST_BPS = 10.0
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
CANONICAL_SIGNATURE = (
    "extra-execution-delay-resilience-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-walk-forward-oos-executed-position|"
    "stress=shift-executed-position-by-one-additional-bar-from-cash|"
    "turnover=absolute-change-in-delayed-position|transaction_cost_bps=10|"
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

    expected = {
        "annualization": ANNUALIZATION,
        "candidate_count": 27,
        "cost_multipliers": [1.0, 2.0, 4.0],
        "non_overlapping_test_folds": True,
        "selection_bars": 730,
        "test_bars": 90,
        "transaction_cost_bps": TRANSACTION_COST_BPS,
    }
    observed = {
        "annualization": base_config.get("annualization"),
        "candidate_count": settings.get("candidate_count"),
        "cost_multipliers": settings.get("cost_multipliers"),
        "non_overlapping_test_folds": settings.get("non_overlapping_test_folds"),
        "selection_bars": settings.get("selection_bars"),
        "test_bars": settings.get("test_bars"),
        "transaction_cost_bps": base_config.get("transaction_cost_bps"),
    }
    if observed != expected:
        raise ValueError(
            "walk-forward settings do not match the predeclared delay stress: "
            f"expected {expected}, got {observed}"
        )


def validate_returns(path: Path, expected_sha256: str) -> pd.DataFrame:
    actual_sha256 = file_sha256(path)
    if actual_sha256 != expected_sha256:
        raise RuntimeError(
            f"returns hash mismatch for {path}: expected {expected_sha256}, got {actual_sha256}"
        )

    frame = pd.read_csv(path)
    required = {
        "timestamp",
        "asset_return",
        "position",
        "turnover",
        "trading_cost",
        "strategy_return",
    }
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

    validated = frame.copy()
    validated["timestamp"] = parsed
    for column in required - {"timestamp"}:
        numeric = pd.to_numeric(validated[column], errors="coerce")
        values = numeric.to_numpy(dtype=float)
        if numeric.isna().any() or not np.isfinite(values).all():
            raise ValueError(f"{column} must contain finite numbers")
        validated[column] = numeric

    positions = validated["position"].to_numpy(dtype=float)
    if np.any(positions < 0.0) or np.any(positions > 1.0):
        raise ValueError("persisted executed positions must remain in [0, 1]")
    returns = validated["asset_return"].to_numpy(dtype=float)
    if np.any(returns <= -1.0):
        raise ValueError("asset returns must be greater than -1")

    expected_turnover = validated["position"].diff().abs()
    expected_turnover.iloc[0] = abs(validated["position"].iloc[0])
    if not np.allclose(
        validated["turnover"].to_numpy(dtype=float),
        expected_turnover.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("persisted turnover does not match executed-position changes")

    expected_cost = validated["turnover"] * (TRANSACTION_COST_BPS / 10_000.0)
    expected_strategy = validated["position"] * validated["asset_return"] - expected_cost
    if not np.allclose(
        validated["trading_cost"].to_numpy(dtype=float),
        expected_cost.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("persisted trading cost does not match declared transaction costs")
    if not np.allclose(
        validated["strategy_return"].to_numpy(dtype=float),
        expected_strategy.to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
    ):
        raise ValueError("persisted strategy return does not reconcile")
    return validated


def apply_extra_execution_delay(
    frame: pd.DataFrame,
    *,
    transaction_cost_bps: float = TRANSACTION_COST_BPS,
) -> pd.DataFrame:
    required = {"timestamp", "asset_return", "position"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"missing delay-stress columns: {sorted(missing)}")
    if not math.isfinite(transaction_cost_bps) or transaction_cost_bps < 0.0:
        raise ValueError("transaction_cost_bps must be finite and non-negative")

    delayed = pd.DataFrame(index=frame.index)
    delayed["timestamp"] = frame["timestamp"]
    delayed["asset_return"] = pd.to_numeric(frame["asset_return"], errors="raise")
    delayed["position"] = pd.to_numeric(frame["position"], errors="raise").shift(1).fillna(0.0)
    delayed["turnover"] = delayed["position"].diff().abs()
    delayed.loc[delayed.index[0], "turnover"] = abs(delayed["position"].iloc[0])
    delayed["trading_cost"] = delayed["turnover"] * (transaction_cost_bps / 10_000.0)
    delayed["strategy_return"] = (
        delayed["position"] * delayed["asset_return"] - delayed["trading_cost"]
    )
    delayed["nav"] = (1.0 + delayed["strategy_return"]).cumprod()
    return delayed


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


def analyze_delayed_returns(values: np.ndarray, seed: int) -> dict[str, object]:
    if values.ndim != 1 or len(values) < BLOCK_LENGTH:
        raise ValueError("delayed returns must be a one-dimensional block-length sample")
    if not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("delayed returns must be finite and greater than -1")

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
        "annualized_mean": float(np.mean(values) * ANNUALIZATION),
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


def analyze_market(frame: pd.DataFrame, seed: int) -> dict[str, object]:
    delayed = apply_extra_execution_delay(frame)
    delayed_result = analyze_delayed_returns(
        delayed["strategy_return"].to_numpy(dtype=float),
        seed,
    )
    delayed_result.update(
        {
            "average_abs_exposure": float(delayed["position"].abs().mean()),
            "cost_drag_sum": float(delayed["trading_cost"].sum()),
            "end": str(delayed["timestamp"].iloc[-1]),
            "original_annualized_mean": float(frame["strategy_return"].mean() * ANNUALIZATION),
            "start": str(delayed["timestamp"].iloc[0]),
            "total_return": float(delayed["nav"].iloc[-1] - 1.0),
        }
    )
    return delayed_result


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
        bool(market_result["bootstrap"]["lower_bound_positive"])
        for market_result in market_results.values()
    )
    failure_reasons = [
        f"{market} delayed-return mean lower confidence bound is not positive"
        for market, market_result in market_results.items()
        if not bool(market_result["bootstrap"]["lower_bound_positive"])
    ]
    return {
        "candidate_count": 1,
        "canonical_signature": CANONICAL_SIGNATURE,
        "claim_boundary": (
            "This is one predeclared execution-latency stress on BTC-USDT and ETH-USDT "
            "development evidence. It shifts the persisted executed OOS position by one "
            "additional daily bar, recomputes turnover and 10 bps costs from cash, and does not "
            "retune signals, candidates, folds, fees, or holdout rules. It is not a fill, spread, "
            "order-book, capacity, or live-execution model."
        ),
        "failure_reasons": failure_reasons,
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, net OOS strategy returns retain a positive "
            "annualized arithmetic mean after the persisted executed position is delayed by one "
            "additional daily bar, with both 95% moving-block-bootstrap lower bounds above zero."
        ),
        "joint_supported": joint_supported,
        "markets": market_results,
        "provenance": {
            "bar": "1Dutc",
            "instrument_type": "spot",
            "provider": "OKX",
            "source_artifact_id": 8515639605,
            "source_artifact_name": "quant-research-426",
            "source_artifact_sha256": (
                "396903281f1ef4ec71edbe0dded7c091c4c3545ffbaa7a502cc15bda4880b478"
            ),
            "source_base_commit": "006df4340a2f0cf73a716255e5148e56856a31cc",
            "source_persistent_head": "43d4f8b10d8f654b5fbcf974793493a967e125e4",
            "source_tested_merge_commit": "8b1003c8b680664f5e96ff6818694c9d30fe1b7f",
            "source_workflow_run_id": 29883451981,
        },
        "settings": {
            "additional_execution_delay_bars": 1,
            "annualization": ANNUALIZATION,
            "block_length": BLOCK_LENGTH,
            "candidate_count": 1,
            "confidence": CONFIDENCE,
            "development_market_screen": True,
            "position_source": "persisted executed OOS position",
            "resamples_per_market": RESAMPLES,
            "transaction_cost_bps": TRANSACTION_COST_BPS,
        },
        "verdict": "supported" if joint_supported else "rejected",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test resilience to one extra execution-delay bar")
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
