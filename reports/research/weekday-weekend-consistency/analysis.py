from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 365
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
    "weekday-weekend-conditional-mean-consistency-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|regimes=weekday,weekend|"
    "metric=conditional-annualized-arithmetic-mean|annualization=365|"
    "resampling=timestamp-return-paired-noncircular-moving-block|block=20|"
    "resamples=2000|confidence=0.95|seeds=BTC:20260722,ETH:20260723|candidate_count=1"
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
    required = {"timestamp", "strategy_return"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    returns = pd.to_numeric(frame["strategy_return"], errors="raise").astype(float)
    if not np.isfinite(returns.to_numpy()).all():
        raise ValueError("strategy returns must be finite")
    return pd.DataFrame({"timestamp": timestamps, "strategy_return": returns})


def regime_labels(timestamps: pd.Series | pd.DatetimeIndex) -> np.ndarray:
    index = pd.DatetimeIndex(timestamps)
    if index.tz is None:
        raise ValueError("timestamps must be timezone-aware")
    weekdays = index.tz_convert("UTC").weekday
    return np.where(weekdays >= 5, "weekend", "weekday")


def moving_block_indices(n: int, *, block_length: int, resamples: int, seed: int) -> np.ndarray:
    if n < block_length:
        raise ValueError("block length cannot exceed observation count")
    rng = np.random.default_rng(seed)
    blocks_per_sample = math.ceil(n / block_length)
    starts = rng.integers(0, n - block_length + 1, size=(resamples, blocks_per_sample))
    offsets = np.arange(block_length)
    indices = starts[..., None] + offsets
    return indices.reshape(resamples, -1)[:, :n]


def conditional_annualized_means(returns: np.ndarray, labels: np.ndarray) -> dict[str, float]:
    output: dict[str, float] = {}
    for regime in ("weekday", "weekend"):
        selected = returns[labels == regime]
        if selected.size == 0:
            raise ValueError(f"no {regime} observations")
        output[regime] = float(selected.mean() * ANNUALIZATION)
    return output


def analyze_market(frame: pd.DataFrame, *, seed: int) -> dict[str, object]:
    returns = frame["strategy_return"].to_numpy(dtype=float)
    labels = regime_labels(frame["timestamp"])
    point = conditional_annualized_means(returns, labels)
    indices = moving_block_indices(
        len(frame), block_length=BLOCK_LENGTH, resamples=RESAMPLES, seed=seed
    )
    distributions = {"weekday": np.empty(RESAMPLES), "weekend": np.empty(RESAMPLES)}
    for sample_index, row_indices in enumerate(indices):
        sample = conditional_annualized_means(returns[row_indices], labels[row_indices])
        for regime in distributions:
            distributions[regime][sample_index] = sample[regime]
    alpha = (1.0 - CONFIDENCE) / 2.0
    regimes: dict[str, object] = {}
    for regime in ("weekday", "weekend"):
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
                "name": "weekday-weekend-conditional-mean-consistency",
                "verdict": "pass" if passed else "reject",
                "failure_reasons": failures,
            }
        ],
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, net rolling OOS returns have a positive "
            "conditional annualized arithmetic mean in weekday and weekend sessions, "
            "with every 95% moving-block-bootstrap lower bound above zero."
        ),
        "economic_rationale": (
            "Crypto liquidity and institutional participation differ between weekdays and "
            "weekends. A robust daily strategy should not depend on only one "
            "calendar-liquidity regime."
        ),
        "method": {
            "annualization": ANNUALIZATION,
            "block_length": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "resampling": "timestamp-return-paired non-circular moving block",
            "regime_definition": "UTC Monday-Friday=weekday; UTC Saturday-Sunday=weekend",
            "metric": "conditional daily arithmetic mean multiplied by 365",
        },
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29891907836,
            "source_artifact_id": 8518541653,
            "source_artifact_name": "quant-research-source-608",
            "source_artifact_sha256": (
                "049c82dff0ed05c37e106d8ac30857532d5f20f18cc9191aaf6f100d3642b7c0"
            ),
            "source_head_sha": "36861294403b51b1ecb41d1586534df7bcf3e0ae",
            "tested_base_sha": "b9efe58b7c804d122658c4dbc27192b0dae1294c",
            "return_file_sha256": {market: spec["sha256"] for market, spec in MARKETS.items()},
        },
        "markets": markets,
        "verdict": "pass" if passed else "reject",
        "failure_reasons": failures,
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "Conditional regime means are descriptive and do not constitute a "
            "trading calendar rule.",
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
