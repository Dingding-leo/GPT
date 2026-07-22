from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 365
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
STRATEGY_COLUMN = "strategy_return"
BENCHMARK_COLUMN = "benchmark_buy_and_hold_return"
CANONICAL_SIGNATURE = (
    "jensen-alpha-vs-buy-and-hold-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|benchmark=buy-and-hold|"
    "regression=strategy-return=alpha+beta*benchmark-return|"
    "metric=annualized-ols-intercept|annualization=365|"
    "claim=alpha>0-in-both-markets|"
    "resampling=paired-noncircular-moving-block-bootstrap|"
    "block=20|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:20260723,ETH-USDT:20260724|candidate_count=1"
)
MARKETS = {
    "BTC-USDT": {
        "seed": 20260723,
        "returns_sha256": (
            "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73"
        ),
    },
    "ETH-USDT": {
        "seed": 20260724,
        "returns_sha256": (
            "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6"
        ),
    },
}
SOURCE = {
    "provider": "OKX",
    "market_type": "spot",
    "timeframe": "1Dutc",
    "workflow_run_id": 29964427149,
    "artifact_id": 8547282774,
    "artifact_name": "quant-research-source-193",
    "artifact_sha256": (
        "e5654461e56bd76f7b61133a4eb9b00b7e98974fc8a09449185614250d462344"
    ),
    "source_head_sha": "e09b3588c9491d2139a52edd5bd2a21c619e9b51",
    "merged_main_sha": "2a8b0ada66a5b2271ebaf1a92f520caa211bf619",
}


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
            f"returns hash mismatch for {path}: expected {expected_sha256}, "
            f"got {actual_sha256}"
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
    if len(parsed) > 1:
        cadence = parsed.diff().iloc[1:]
        if not cadence.eq(pd.Timedelta(days=1)).all():
            raise ValueError("timestamps must have exact daily cadence")

    returns = frame[[STRATEGY_COLUMN, BENCHMARK_COLUMN]].apply(
        pd.to_numeric,
        errors="coerce",
    )
    values = returns.to_numpy(dtype=float)
    if returns.isna().any().any() or not np.isfinite(values).all():
        raise ValueError("return columns must contain only finite numeric values")
    if np.any(values <= -1.0):
        raise ValueError("returns must be greater than -1")

    validated = returns.copy()
    validated.insert(0, "timestamp", parsed)
    return validated


def annualized_jensen_alpha(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    annualization: int = ANNUALIZATION,
) -> tuple[float, float]:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if strategy.ndim != 1 or benchmark.ndim != 1 or len(strategy) != len(benchmark):
        raise ValueError("strategy and benchmark returns must be aligned one-dimensional arrays")
    if len(strategy) < 3:
        raise ValueError("at least three aligned observations are required")
    if not np.isfinite(strategy).all() or not np.isfinite(benchmark).all():
        raise ValueError("returns must be finite")
    if np.var(benchmark) == 0.0:
        raise ValueError("benchmark returns must have non-zero variance")

    design = np.column_stack((np.ones(len(benchmark)), benchmark))
    alpha_daily, beta = np.linalg.lstsq(design, strategy, rcond=None)[0]
    return float(alpha_daily * annualization), float(beta)


def moving_block_indices(
    observation_count: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if observation_count < 1:
        raise ValueError("observation_count must be positive")
    if block_length < 1 or block_length > observation_count:
        raise ValueError("block_length must be between 1 and observation_count")

    starts = np.arange(observation_count - block_length + 1)
    indices: list[int] = []
    while len(indices) < observation_count:
        start = int(rng.choice(starts))
        indices.extend(range(start, start + block_length))
    return np.asarray(indices[:observation_count], dtype=int)


def analyze_market(frame: pd.DataFrame, seed: int) -> dict[str, object]:
    strategy = frame[STRATEGY_COLUMN].to_numpy(dtype=float)
    benchmark = frame[BENCHMARK_COLUMN].to_numpy(dtype=float)
    alpha, beta = annualized_jensen_alpha(strategy, benchmark)

    rng = np.random.default_rng(seed)
    bootstrap_alpha = np.empty(RESAMPLES, dtype=float)
    bootstrap_beta = np.empty(RESAMPLES, dtype=float)
    for sample_index in range(RESAMPLES):
        indices = moving_block_indices(len(frame), BLOCK_LENGTH, rng)
        sample_alpha, sample_beta = annualized_jensen_alpha(
            strategy[indices],
            benchmark[indices],
        )
        bootstrap_alpha[sample_index] = sample_alpha
        bootstrap_beta[sample_index] = sample_beta

    tail_probability = (1.0 - CONFIDENCE) / 2.0
    alpha_lower, alpha_upper = np.quantile(
        bootstrap_alpha,
        [tail_probability, 1.0 - tail_probability],
    )
    beta_lower, beta_upper = np.quantile(
        bootstrap_beta,
        [tail_probability, 1.0 - tail_probability],
    )

    return {
        "observations": int(len(frame)),
        "start": frame["timestamp"].iloc[0].isoformat(),
        "end": frame["timestamp"].iloc[-1].isoformat(),
        "annualized_jensen_alpha": alpha,
        "beta": beta,
        "alpha_confidence_interval": {
            "lower": float(alpha_lower),
            "upper": float(alpha_upper),
        },
        "beta_confidence_interval": {
            "lower": float(beta_lower),
            "upper": float(beta_upper),
        },
        "probability_alpha_positive": float(np.mean(bootstrap_alpha > 0.0)),
        "passes": bool(alpha_lower > 0.0),
    }


def run_analysis(artifact_dir: Path) -> dict[str, object]:
    market_results: dict[str, object] = {}
    for market, settings in MARKETS.items():
        path = artifact_dir / market / "walk_forward_returns.csv"
        frame = validate_returns(path, str(settings["returns_sha256"]))
        result = analyze_market(frame, int(settings["seed"]))
        result["returns_sha256"] = str(settings["returns_sha256"])
        market_results[market] = result

    passed = all(bool(result["passes"]) for result in market_results.values())
    failure_reasons = [
        (
            f"{market} annualized Jensen alpha lower confidence bound "
            f"{float(result['alpha_confidence_interval']['lower']):.12f} "
            "is not strictly positive"
        )
        for market, result in market_results.items()
        if not bool(result["passes"])
    ]
    return {
        "hypothesis": (
            "BTC-USDT and ETH-USDT net rolling OOS strategy returns each have "
            "positive annualized Jensen alpha versus persisted net buy-and-hold."
        ),
        "canonical_signature": CANONICAL_SIGNATURE,
        "candidate_accounting": {
            "searched": 1,
            "passed": int(passed),
            "rejected": int(not passed),
        },
        "method": {
            "benchmark": "persisted net buy-and-hold",
            "regression": "strategy_return = alpha + beta * benchmark_return",
            "metric": "annualized OLS intercept",
            "annualization": ANNUALIZATION,
            "block_length": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "paired_rows": True,
            "noncircular_blocks": True,
        },
        "source": SOURCE,
        "markets": market_results,
        "verdict": "supported" if passed else "rejected",
        "failure_reasons": failure_reasons,
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "A linear one-factor regression is descriptive and does not prove causal alpha.",
            "Moving-block concatenation creates artificial joins between observed blocks.",
            "The analysis does not model nonlinear impact, capacity, latency, or partial fills.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = run_analysis(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
