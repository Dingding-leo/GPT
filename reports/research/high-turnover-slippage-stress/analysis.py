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
HIGH_TURNOVER_FRACTION = 0.10
EXTRA_SLIPPAGE_BPS = 20.0
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
    "high-turnover-concentrated-slippage-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-turnover-and-returns|"
    "stress=extra-20bps-per-unit-turnover-on-ceil-top-10pct-turnover-rows-per-sample|"
    "metric=annualized-arithmetic-mean-stressed-net-return|annualization=365|"
    "resampling=turnover-return-paired-noncircular-moving-block|block=20|"
    "resamples=2000|confidence=0.95|seeds=BTC:20260722,ETH:20260723|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _explicit_utc_index(values: pd.Series) -> pd.DatetimeIndex:
    parsed: list[pd.Timestamp] = []
    for value in values:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("timestamps must contain explicit timezone information")
        parsed.append(timestamp)
    index = pd.DatetimeIndex(pd.to_datetime(parsed, utc=True))
    if index.duplicated().any() or not index.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    return index


def load_observations(path: Path, *, expected_sha256: str) -> pd.DataFrame:
    actual = file_sha256(path)
    if actual != expected_sha256:
        raise ValueError(f"return file hash mismatch: expected {expected_sha256}, actual {actual}")
    frame = pd.read_csv(path)
    required = {"timestamp", "turnover", "strategy_return"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")
    timestamps = _explicit_utc_index(frame["timestamp"])
    turnover = pd.to_numeric(frame["turnover"], errors="raise").to_numpy(dtype=float)
    returns = pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(turnover).all() or (turnover < 0.0).any():
        raise ValueError("turnover must be finite and non-negative")
    if not np.isfinite(returns).all() or (returns <= -1.0).any():
        raise ValueError("strategy returns must be finite and greater than -100%")
    return pd.DataFrame({"timestamp": timestamps, "turnover": turnover, "strategy_return": returns})


def moving_block_indices(n: int, *, block_length: int, resamples: int, seed: int) -> np.ndarray:
    if n < block_length:
        raise ValueError("block length cannot exceed observation count")
    rng = np.random.default_rng(seed)
    blocks_per_sample = math.ceil(n / block_length)
    starts = rng.integers(0, n - block_length + 1, size=(resamples, blocks_per_sample))
    offsets = np.arange(block_length)
    indices = starts[..., None] + offsets
    return indices.reshape(resamples, -1)[:, :n]


def apply_concentrated_slippage(
    turnover: np.ndarray,
    returns: np.ndarray,
    *,
    high_turnover_fraction: float = HIGH_TURNOVER_FRACTION,
    extra_slippage_bps: float = EXTRA_SLIPPAGE_BPS,
) -> tuple[np.ndarray, int]:
    turnover = np.asarray(turnover, dtype=float)
    returns = np.asarray(returns, dtype=float)
    if turnover.ndim != 1 or returns.ndim != 1 or len(turnover) != len(returns):
        raise ValueError("turnover and returns must be aligned one-dimensional arrays")
    if len(turnover) < 2:
        raise ValueError("at least two observations are required")
    if not 0.0 < high_turnover_fraction < 1.0:
        raise ValueError("high_turnover_fraction must be inside (0, 1)")
    if not math.isfinite(extra_slippage_bps) or extra_slippage_bps < 0.0:
        raise ValueError("extra_slippage_bps must be finite and non-negative")
    if not np.isfinite(turnover).all() or (turnover < 0.0).any():
        raise ValueError("turnover must be finite and non-negative")
    if not np.isfinite(returns).all():
        raise ValueError("returns must be finite")

    stressed_count = math.ceil(len(turnover) * high_turnover_fraction)
    ranking = np.argsort(turnover, kind="stable")
    stressed = returns.copy()
    stressed_rows = ranking[-stressed_count:]
    stressed[stressed_rows] -= turnover[stressed_rows] * extra_slippage_bps / 10_000.0
    return stressed, stressed_count


def analyze_market(frame: pd.DataFrame, *, seed: int) -> dict[str, object]:
    turnover = frame["turnover"].to_numpy(dtype=float)
    returns = frame["strategy_return"].to_numpy(dtype=float)
    stressed, stressed_count = apply_concentrated_slippage(turnover, returns)
    point = float(stressed.mean() * ANNUALIZATION)

    indices = moving_block_indices(
        len(frame), block_length=BLOCK_LENGTH, resamples=RESAMPLES, seed=seed
    )
    distribution = np.empty(RESAMPLES)
    for sample_index, row_indices in enumerate(indices):
        sampled_stressed, sampled_count = apply_concentrated_slippage(
            turnover[row_indices], returns[row_indices]
        )
        if sampled_count != stressed_count:
            raise RuntimeError("resampled stress count changed unexpectedly")
        distribution[sample_index] = sampled_stressed.mean() * ANNUALIZATION

    alpha = (1.0 - CONFIDENCE) / 2.0
    lower, upper = np.quantile(distribution, [alpha, 1.0 - alpha])
    return {
        "observations": len(frame),
        "start": frame["timestamp"].iloc[0].isoformat(),
        "end": frame["timestamp"].iloc[-1].isoformat(),
        "seed": seed,
        "stressed_observations": stressed_count,
        "full_sample_annualized_arithmetic_mean": float(returns.mean() * ANNUALIZATION),
        "stressed_annualized_arithmetic_mean": point,
        "confidence_interval": {"lower": float(lower), "upper": float(upper)},
        "probability_mean_positive": float((distribution > 0.0).mean()),
        "passes": bool(lower > 0.0),
    }


def build_result(artifact_dir: Path) -> dict[str, object]:
    markets: dict[str, object] = {}
    failures: list[str] = []
    for market, specification in MARKETS.items():
        path = artifact_dir / market / "walk_forward_returns.csv"
        frame = load_observations(path, expected_sha256=specification["sha256"])
        market_result = analyze_market(frame, seed=specification["seed"])
        markets[market] = market_result
        if not market_result["passes"]:
            failures.append(
                f"{market} stressed-mean 95% lower bound is non-positive: "
                f"{market_result['confidence_interval']['lower']:.12f}"
            )

    passed = not failures
    return {
        "canonical_signature": SIGNATURE,
        "candidate_count": 1,
        "candidates": [
            {
                "name": "extra-slippage-on-highest-turnover-decile",
                "verdict": "pass" if passed else "reject",
                "failure_reasons": failures,
            }
        ],
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, net rolling OOS returns retain a positive "
            "annualized arithmetic mean after charging an additional 20 bps per unit of "
            "turnover on the highest-turnover 10% of observations, with both 95% "
            "moving-block-bootstrap lower bounds above zero."
        ),
        "economic_rationale": (
            "Large position changes are the observations most exposed to spread widening, "
            "slippage, and nonlinear market impact. A robust research result should not "
            "require optimistic execution costs on its highest-turnover sessions."
        ),
        "method": {
            "annualization": ANNUALIZATION,
            "block_length": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "high_turnover_fraction": HIGH_TURNOVER_FRACTION,
            "extra_slippage_bps_per_unit_turnover": EXTRA_SLIPPAGE_BPS,
            "stress_selection": (
                "remove no observations; identify exactly ceil(10% * n) highest-turnover "
                "rows inside the observed sample and each resample, using stable row-order "
                "tie breaking, then subtract turnover * 20 bps from persisted net return"
            ),
            "resampling": "turnover-return-paired non-circular moving block",
            "metric": "daily stressed net-return arithmetic mean multiplied by 365",
        },
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29894309496,
            "source_workflow_run_attempt": 2,
            "source_artifact_id": 8519440629,
            "source_artifact_name": "quant-research-source-631-attempt-2",
            "source_artifact_sha256": (
                "73991c41492bd0ffe101f3ea86149e67751b15724854a73bc9dbb6762fd7c0b4"
            ),
            "source_head_sha": "a944956c4859dafc59a7364c3b98d0e26b9d0e96",
            "tested_base_sha": "18ba522be8a7bf3941392a8acfc7f5100172fc91",
            "return_file_sha256": {market: spec["sha256"] for market, spec in MARKETS.items()},
        },
        "markets": markets,
        "verdict": "pass" if passed else "reject",
        "failure_reasons": failures,
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "The stress is a fixed diagnostic, not a calibrated exchange-impact model.",
            "The analysis does not estimate capacity, order-book depth, latency, or partial fills.",
            (
                "The highest-turnover set is recomputed inside each resample and is not a "
                "trading rule."
            ),
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
