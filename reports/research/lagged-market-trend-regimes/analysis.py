from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 365
TREND_LOOKBACK = 90
BLOCK_LENGTH = 20
RESAMPLES = 2000
CONFIDENCE = 0.95
MARKETS = {
    "BTC-USDT": {
        "seed": 20260722,
        "sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
    },
}
SIGNATURE = (
    "lagged-market-trend-regime-consistency-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-asset-and-strategy-returns|"
    "regimes=prior-90d-compounded-asset-return-positive-vs-nonpositive|"
    "trend=asset-return-shift1-rolling-product-90-minus1|"
    "metric=conditional-annualized-arithmetic-mean-net-return|annualization=365|"
    "resampling=asset-strategy-return-paired-noncircular-moving-block-with-trend-recomputed|"
    "block=20|resamples=2000|confidence=0.95|"
    "seeds=BTC:20260722,ETH:20260723|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_returns(path: Path, *, expected_sha256: str) -> pd.DataFrame:
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise ValueError(f"return file hash mismatch: expected {expected_sha256}, actual {actual}")
    frame = pd.read_csv(path)
    required = {"timestamp", "asset_return", "strategy_return"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = (
            timestamps.iloc[1:].reset_index(drop=True)
            - timestamps.iloc[:-1].reset_index(drop=True)
        )
        if not bool((intervals == pd.Timedelta(days=1)).all()):
            raise ValueError("timestamps must have exact daily cadence")
    asset_returns = pd.to_numeric(frame["asset_return"], errors="raise").astype(float)
    strategy_returns = pd.to_numeric(frame["strategy_return"], errors="raise").astype(float)
    if not np.isfinite(asset_returns.to_numpy()).all():
        raise ValueError("asset returns must be finite")
    if not np.isfinite(strategy_returns.to_numpy()).all():
        raise ValueError("strategy returns must be finite")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "asset_return": asset_returns,
            "strategy_return": strategy_returns,
        }
    )


def lagged_trend_labels(asset_returns: np.ndarray, *, lookback: int = TREND_LOOKBACK) -> np.ndarray:
    if lookback < 2:
        raise ValueError("trend lookback must be at least 2")
    if asset_returns.ndim != 1 or len(asset_returns) <= lookback:
        raise ValueError("asset return series is too short for the trend lookback")
    if not np.isfinite(asset_returns).all() or (asset_returns <= -1.0).any():
        raise ValueError("asset returns must be finite and greater than -100%")
    series = pd.Series(asset_returns, dtype=float)
    lagged_growth = (1.0 + series.shift(1)).rolling(lookback).apply(np.prod, raw=True) - 1.0
    labels = np.full(len(series), "warmup", dtype=object)
    eligible = lagged_growth.notna().to_numpy()
    labels[eligible & lagged_growth.gt(0.0).to_numpy()] = "positive_trend"
    labels[eligible & lagged_growth.le(0.0).to_numpy()] = "nonpositive_trend"
    return labels.astype(str)


def moving_block_indices(n: int, *, block_length: int, resamples: int, seed: int) -> np.ndarray:
    if n < block_length:
        raise ValueError("block length cannot exceed observation count")
    rng = np.random.default_rng(seed)
    blocks_per_sample = math.ceil(n / block_length)
    starts = rng.integers(0, n - block_length + 1, size=(resamples, blocks_per_sample))
    offsets = np.arange(block_length)
    indices = starts[..., None] + offsets
    return indices.reshape(resamples, -1)[:, :n]


def conditional_annualized_means(
    strategy_returns: np.ndarray,
    labels: np.ndarray,
) -> dict[str, float]:
    output: dict[str, float] = {}
    for regime in ("positive_trend", "nonpositive_trend"):
        selected = strategy_returns[labels == regime]
        if selected.size == 0:
            raise ValueError(f"no {regime} observations")
        output[regime] = float(selected.mean() * ANNUALIZATION)
    return output


def analyze_market(frame: pd.DataFrame, *, seed: int) -> dict[str, object]:
    asset_returns = frame["asset_return"].to_numpy(dtype=float)
    strategy_returns = frame["strategy_return"].to_numpy(dtype=float)
    labels = lagged_trend_labels(asset_returns)
    point = conditional_annualized_means(strategy_returns, labels)
    indices = moving_block_indices(
        len(frame), block_length=BLOCK_LENGTH, resamples=RESAMPLES, seed=seed
    )
    distributions = {
        "positive_trend": np.empty(RESAMPLES),
        "nonpositive_trend": np.empty(RESAMPLES),
    }
    for sample_index, row_indices in enumerate(indices):
        sample_asset = asset_returns[row_indices]
        sample_strategy = strategy_returns[row_indices]
        sample_labels = lagged_trend_labels(sample_asset)
        sample = conditional_annualized_means(sample_strategy, sample_labels)
        for regime in distributions:
            distributions[regime][sample_index] = sample[regime]
    alpha = (1.0 - CONFIDENCE) / 2.0
    regimes: dict[str, object] = {}
    for regime in ("positive_trend", "nonpositive_trend"):
        distribution = distributions[regime]
        lower, upper = np.quantile(distribution, [alpha, 1.0 - alpha])
        regimes[regime] = {
            "observations": int((labels == regime).sum()),
            "annualized_arithmetic_mean": point[regime],
            "confidence_interval": {"lower": float(lower), "upper": float(upper)},
            "probability_mean_positive": float((distribution > 0.0).mean()),
            "passes": bool(lower > 0.0),
        }
    return {
        "observations": len(frame),
        "eligible_observations": int((labels != "warmup").sum()),
        "warmup_observations": int((labels == "warmup").sum()),
        "start": frame["timestamp"].iloc[0].isoformat(),
        "end": frame["timestamp"].iloc[-1].isoformat(),
        "seed": seed,
        "regimes": regimes,
    }


def build_result(artifact_dir: Path) -> dict[str, object]:
    markets: dict[str, object] = {}
    failures: list[str] = []
    for market, specification in MARKETS.items():
        returns_path = artifact_dir / market / "walk_forward_returns.csv"
        frame = load_returns(returns_path, expected_sha256=specification["sha256"])
        result = analyze_market(frame, seed=specification["seed"])
        markets[market] = result
        for regime, values in result["regimes"].items():
            if not values["passes"]:
                failures.append(
                    f"{market} {regime} 95% lower bound is non-positive: "
                    f"{values['confidence_interval']['lower']:.12f}"
                )
    passed = not failures
    return {
        "canonical_signature": SIGNATURE,
        "candidate_count": 1,
        "candidates": [
            {
                "name": "lagged-market-trend-regime-consistency",
                "verdict": "pass" if passed else "reject",
                "failure_reasons": failures,
            }
        ],
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, net rolling OOS returns have a positive "
            "conditional annualized arithmetic mean when the prior 90-day compounded "
            "asset return is positive and when it is non-positive, with every 95% "
            "moving-block-bootstrap lower bound above zero."
        ),
        "economic_rationale": (
            "A credible long/cash strategy should not require only an established rising "
            "market or only a flat/falling market to produce positive net returns. The "
            "regime uses only asset returns available before each evaluated session."
        ),
        "method": {
            "annualization": ANNUALIZATION,
            "trend_lookback": TREND_LOOKBACK,
            "block_length": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "resampling": (
                "asset-return and strategy-return paired non-circular moving blocks; "
                "lagged trend recomputed inside every sample"
            ),
            "regime_definition": (
                "positive_trend if compounded asset return over the previous 90 sessions "
                "is above zero; otherwise nonpositive_trend"
            ),
            "metric": "conditional daily arithmetic mean multiplied by 365",
        },
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29897472573,
            "source_artifact_id": 8520542295,
            "source_artifact_name": "quant-research-source-668-attempt-1",
            "source_artifact_sha256": (
                "9dd429dfab4e7644b7b7e1113ea1dcd7dfbcde5968974ed64e3ef176597dd73d"
            ),
            "source_head_sha": "019823ff335d53247589ba8345298db4a93307d1",
            "tested_base_sha": "f163f5863205ef642bd7a532c46ab142e111c60e",
            "merged_main_sha": "fc2100fa5ae4f815828960326405e7d171d59891",
            "return_file_sha256": {market: spec["sha256"] for market, spec in MARKETS.items()},
        },
        "markets": markets,
        "verdict": "pass" if passed else "reject",
        "failure_reasons": failures,
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "The trend split is a descriptive mechanism diagnostic, not a trading rule.",
            (
                "Moving-block concatenation creates artificial joins; trend is recomputed "
                "after resampling."
            ),
            "The analysis does not model spread, impact, capacity, latency, or partial fills.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
