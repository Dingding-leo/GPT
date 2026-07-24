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
        "report_sha256": "4b326e6b7553ee4914dadaad48c909d93b2cde7a20b053d18e2db77f9241c203",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "e80e2c2087951dae66771110ba363a5e798da0638e84cf5af1d07736bb31baeb",
    },
}
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
TAIL_PROBABILITY = 0.10
RETURN_COLUMN = "asset_return"
POSITION_COLUMN = "position"
CANONICAL_SIGNATURE = (
    "worst-decile-exposure-timing-v1|markets=BTC-USDT,ETH-USDT|"
    "tail=asset-return-bottom-decile-recomputed-per-resample|"
    "metric=mean-position-nontail-minus-tail|position=persisted-executed-oos|"
    "block=20|resamples=2000|confidence=0.95|"
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
        "annualization": 365,
        "candidate_count": 27,
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
    required = {"timestamp", RETURN_COLUMN, POSITION_COLUMN}
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

    numeric = frame[[RETURN_COLUMN, POSITION_COLUMN]].apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy(dtype=float)
    if numeric.isna().any().any() or not np.isfinite(values).all():
        raise ValueError("asset returns and positions must be finite numbers")
    returns = numeric[RETURN_COLUMN].to_numpy(dtype=float)
    if np.any(returns <= -1.0):
        raise ValueError("asset returns must be greater than -1")
    positions = numeric[POSITION_COLUMN].to_numpy(dtype=float)
    if np.any((positions < 0.0) | (positions > 1.0)):
        raise ValueError("positions must stay within the declared long/cash range [0, 1]")

    validated = frame.copy()
    validated["timestamp"] = parsed
    validated[[RETURN_COLUMN, POSITION_COLUMN]] = numeric
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


def tail_exposure_metrics(
    asset_returns: np.ndarray,
    positions: np.ndarray,
    tail_probability: float = TAIL_PROBABILITY,
) -> dict[str, float | int]:
    if asset_returns.shape != positions.shape:
        raise ValueError("asset_returns and positions must have identical shape")
    if asset_returns.ndim != 1 or len(asset_returns) == 0:
        raise ValueError("asset_returns and positions must be non-empty one-dimensional arrays")
    if not np.isfinite(asset_returns).all() or np.any(asset_returns <= -1.0):
        raise ValueError("asset_returns must contain finite values greater than -1")
    if not np.isfinite(positions).all() or np.any((positions < 0.0) | (positions > 1.0)):
        raise ValueError("positions must be finite and within [0, 1]")
    if not math.isfinite(tail_probability) or not 0.0 < tail_probability < 0.5:
        raise ValueError("tail_probability must be finite and within (0, 0.5)")

    threshold = float(np.quantile(asset_returns, tail_probability))
    tail = asset_returns <= threshold
    if not tail.any() or tail.all():
        raise ValueError("tail split must contain both tail and non-tail observations")

    tail_position = float(np.mean(positions[tail]))
    non_tail_position = float(np.mean(positions[~tail]))
    return {
        "exposure_delta": non_tail_position - tail_position,
        "non_tail_mean_position": non_tail_position,
        "non_tail_observations": int((~tail).sum()),
        "tail_mean_position": tail_position,
        "tail_observations": int(tail.sum()),
        "tail_return_threshold": threshold,
    }


def analyze_market(frame: pd.DataFrame, seed: int) -> dict[str, object]:
    asset_returns = frame[RETURN_COLUMN].to_numpy(dtype=float)
    positions = frame[POSITION_COLUMN].to_numpy(dtype=float)
    point = tail_exposure_metrics(asset_returns, positions)

    deltas = np.empty(RESAMPLES, dtype=float)
    rng = np.random.default_rng(seed)
    for sample_number in range(RESAMPLES):
        indices = moving_block_indices(len(asset_returns), BLOCK_LENGTH, rng)
        sampled = tail_exposure_metrics(asset_returns[indices], positions[indices])
        deltas[sample_number] = float(sampled["exposure_delta"])

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
            "development markets. Same-day tail labels are used only after returns occur to audit "
            "whether already-executed positions were lower before severe sessions; they are not a "
            "tradable signal or untouched-holdout result."
        ),
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, the mean executed OOS position on the asset's "
            "worst-decile return days is lower than on all other days, with a positive 95% paired "
            "moving-block-bootstrap lower bound for non-tail minus tail exposure."
        ),
        "joint_supported": joint_supported,
        "markets": market_results,
        "provenance": {
            "bar": "1Dutc",
            "instrument_type": "spot",
            "provider": "OKX",
            "source_artifact_id": 8512566174,
            "source_artifact_name": "quant-research-354",
            "source_artifact_sha256": (
                "288c19af640e03f8b69e20edd61002c04a7e007ee1973cab287224a0a687b15f"
            ),
            "source_base_commit": "60251e9d945be29645aca86d4133e18ae9a90652",
            "source_persistent_head": "df8dd830d10f225c27edae41cccda0ae3592939e",
            "source_tested_commit": "5fdcffbd0b3ba38c0d25b5502807fb1814202b8d",
            "source_workflow_run_id": 29874768418,
        },
        "settings": {
            "block_length": BLOCK_LENGTH,
            "candidate_count": 1,
            "confidence": CONFIDENCE,
            "development_market_screen": True,
            "markets": list(MARKETS),
            "position_definition": "persisted executed OOS position, already lagged by one bar",
            "primary_metric": "mean_position_nontail_minus_tail",
            "resamples": RESAMPLES,
            "resampling": "paired moving block bootstrap without circular wrapping",
            "seed_rule": "20260722 for BTC-USDT and 20260723 for ETH-USDT",
            "tail_definition": "bottom 10% of asset returns, threshold recomputed per resample",
            "tail_probability": TAIL_PROBABILITY,
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
