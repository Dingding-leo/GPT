from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
STRATEGY_COLUMN = "strategy_return"
BENCHMARK_COLUMN = "benchmark_volatility_targeted_long_return"
FOLD_COLUMN = "fold"
TAIL_FRACTION = 0.05
COMPLETE_FOLD_SIZE = 90
FOLD_BLOCK_LENGTH = 3
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072321, "ETH-USDT": 2026072322}
VOLATILITY_LOOKBACK = 30
TARGET_VOLATILITY = 0.50
MAX_POSITION = 1.0
ANNUALIZATION = 365
TRANSACTION_COST_BPS = 10.0
RECONSTRUCTION_TOLERANCE = 5e-15
EXPECTED_RETURN_FILE_SHA256 = {
    "BTC-USDT": "ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce",
    "ETH-USDT": "bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047",
}
EXPECTED_SNAPSHOT_FILE_SHA256 = {
    "BTC-USDT": "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1",
    "ETH-USDT": "842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f",
}
SOURCE = {
    "provider": "OKX",
    "market_type": "spot",
    "timeframe": "1Dutc",
    "workflow_run_id": 29994613190,
    "artifact_id": 8558445273,
    "artifact_name": "quant-research-source-1826-attempt-1",
    "artifact_sha256": ("8c89b8ecc4904cba018ac95079305c46e25d92199242b95d3aeffaad1bc0799c"),
    "source_head_sha": "348cfd30df9a0665b5b129fba32edaafc8a2428e",
}
CANONICAL_SIGNATURE = (
    "prior-fold-volatility-matched-expected-shortfall-vs-volatility-benchmark-v2|"
    "markets=BTC-USDT,ETH-USDT|source=immutable-OKX-snapshots-and-persisted-net-"
    "rolling-oos-returns|benchmark=volatility-targeted-long-position-reconstructed-"
    "from-snapshot-and-scaled-in-fold-t-by-sample-volatility-ratio-estimated-from-"
    "complete-fold-t-minus-1|volatility=sample-standard-deviation-ddof1|"
    "execution=one-bar-delay-10bps-cost-recomputed-from-scaled-position-with-"
    "continuous-fold-boundaries-and-cash-entry-at-evaluation-start|"
    "evaluation=complete-folds-2-through-26|trailing-short-fold=excluded|"
    "metric=mean-worst-ceil-5pct-returns|tail-fraction=0.05|"
    "claim=strategy-minus-scaled-benchmark-expected-shortfall>0-in-both-markets|"
    "resampling=noncircular-moving-block-bootstrap-over-observed-complete-folds|"
    "fold-block-length=3|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072321,ETH-USDT:2026072322|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_timestamps(values: pd.Series) -> pd.DatetimeIndex:
    raw = values.astype("string")
    explicit_zone = raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if not bool(explicit_zone.all()):
        raise ValueError("timestamps must include an explicit timezone offset")
    timestamps = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        cadence = timestamps[1:] - timestamps[:-1]
        if not bool((cadence == pd.Timedelta(days=1)).all()):
            raise ValueError("timestamps must have exact daily cadence")
    return timestamps


def load_returns(path: str | Path, market: str, *, verify_hash: bool = True) -> pd.DataFrame:
    if market not in MARKETS:
        raise ValueError(f"unsupported market: {market}")
    if verify_hash:
        observed_hash = file_sha256(path)
        expected_hash = EXPECTED_RETURN_FILE_SHA256[market]
        if observed_hash != expected_hash:
            raise ValueError(
                f"{market} return file SHA-256 mismatch: "
                f"expected {expected_hash}, observed {observed_hash}"
            )
    frame = pd.read_csv(path)
    required = {"timestamp", FOLD_COLUMN, STRATEGY_COLUMN, BENCHMARK_COLUMN}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")
    validated = pd.DataFrame({"timestamp": _validated_timestamps(frame["timestamp"])})
    folds = pd.to_numeric(frame[FOLD_COLUMN], errors="coerce")
    if folds.isna().any() or not np.equal(folds, np.floor(folds)).all():
        raise ValueError("fold identifiers must be finite integers")
    validated[FOLD_COLUMN] = folds.astype(int)
    for column in (STRATEGY_COLUMN, BENCHMARK_COLUMN):
        values = pd.to_numeric(frame[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise ValueError(f"{column} must contain only finite numeric values")
        if bool((values <= -1.0).any()):
            raise ValueError(f"{column} must be greater than -1")
        validated[column] = values.astype(float)
    return validated


def load_snapshot(path: str | Path, market: str, *, verify_hash: bool = True) -> pd.DataFrame:
    if market not in MARKETS:
        raise ValueError(f"unsupported market: {market}")
    if verify_hash:
        observed_hash = file_sha256(path)
        expected_hash = EXPECTED_SNAPSHOT_FILE_SHA256[market]
        if observed_hash != expected_hash:
            raise ValueError(
                f"{market} snapshot SHA-256 mismatch: "
                f"expected {expected_hash}, observed {observed_hash}"
            )
    frame = pd.read_csv(path)
    required = {"timestamp", "close", "confirm"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"snapshot file is missing required columns: {sorted(missing)}")
    timestamps = _validated_timestamps(frame["timestamp"])
    close = pd.to_numeric(frame["close"], errors="coerce")
    confirm = pd.to_numeric(frame["confirm"], errors="coerce")
    if close.isna().any() or not np.isfinite(close.to_numpy(dtype=float)).all():
        raise ValueError("snapshot close must contain only finite numeric values")
    if bool((close <= 0.0).any()):
        raise ValueError("snapshot close must be strictly positive")
    if confirm.isna().any() or not bool((confirm == 1).all()):
        raise ValueError("snapshot must contain only confirmed candles")
    return pd.DataFrame({"timestamp": timestamps, "close": close.astype(float)})


def reconstruct_volatility_benchmark(
    snapshot: pd.DataFrame,
    returns: pd.DataFrame,
) -> tuple[pd.DataFrame, float]:
    prices = snapshot.set_index("timestamp")["close"]
    log_returns = np.log(prices).diff()
    realized = log_returns.rolling(VOLATILITY_LOOKBACK, min_periods=VOLATILITY_LOOKBACK).std(
        ddof=0
    ) * np.sqrt(ANNUALIZATION)
    target = (TARGET_VOLATILITY / realized.replace(0.0, np.nan)).clip(0.0, MAX_POSITION)
    position = target.shift(1).fillna(0.0)
    asset_return = prices.pct_change().fillna(0.0)
    full = pd.DataFrame(
        {
            "timestamp": prices.index,
            "benchmark_position": position.to_numpy(dtype=float),
            "asset_return": asset_return.to_numpy(dtype=float),
        }
    )
    aligned = returns[["timestamp", BENCHMARK_COLUMN]].merge(
        full,
        on="timestamp",
        how="left",
        validate="one_to_one",
    )
    if aligned[["benchmark_position", "asset_return"]].isna().any().any():
        raise ValueError("snapshot does not fully cover the rolling OOS timestamps")
    turnover = aligned["benchmark_position"].diff().abs()
    turnover.iloc[0] = abs(float(aligned["benchmark_position"].iloc[0]))
    rebuilt = (
        aligned["benchmark_position"] * aligned["asset_return"]
        - turnover * TRANSACTION_COST_BPS / 10_000.0
    )
    error = np.abs(rebuilt.to_numpy() - aligned[BENCHMARK_COLUMN].to_numpy())
    max_error = float(error.max())
    if max_error > RECONSTRUCTION_TOLERANCE:
        raise ValueError(
            "reconstructed volatility benchmark does not match persisted returns: "
            f"max_abs_error={max_error}"
        )
    return aligned[["timestamp", "benchmark_position", "asset_return"]].copy(), max_error


def complete_folds(frame: pd.DataFrame) -> list[int]:
    ordered = list(dict.fromkeys(frame[FOLD_COLUMN].tolist()))
    if ordered != sorted(ordered) or ordered != list(range(ordered[0], ordered[-1] + 1)):
        raise ValueError("fold identifiers must be contiguous and increasing")
    sizes = frame.groupby(FOLD_COLUMN, sort=False).size().to_dict()
    incomplete = [fold for fold in ordered if sizes[fold] != COMPLETE_FOLD_SIZE]
    if incomplete:
        if len(incomplete) != 1 or incomplete[0] != ordered[-1]:
            raise ValueError("only one trailing incomplete fold is allowed")
        if sizes[incomplete[0]] >= COMPLETE_FOLD_SIZE:
            raise ValueError("the trailing incomplete fold must be shorter than 90 rows")
    completed = [fold for fold in ordered if sizes[fold] == COMPLETE_FOLD_SIZE]
    if len(completed) < 2:
        raise ValueError("at least two complete folds are required")
    return completed


def prior_fold_scaled_returns(
    frame: pd.DataFrame,
    benchmark: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[int, float]]:
    if not frame["timestamp"].equals(benchmark["timestamp"]):
        raise ValueError("returns and reconstructed benchmark timestamps must align exactly")
    working = frame.merge(benchmark, on="timestamp", validate="one_to_one")
    folds = complete_folds(working)
    pieces: list[pd.DataFrame] = []
    scales: dict[int, float] = {}
    for current_fold in folds[1:]:
        previous = working.loc[working[FOLD_COLUMN] == current_fold - 1]
        current = working.loc[working[FOLD_COLUMN] == current_fold].copy()
        strategy_volatility = float(previous[STRATEGY_COLUMN].std(ddof=1))
        benchmark_volatility = float(previous[BENCHMARK_COLUMN].std(ddof=1))
        if not math.isfinite(strategy_volatility) or strategy_volatility < 0.0:
            raise ValueError("previous-fold strategy volatility must be finite and non-negative")
        if not math.isfinite(benchmark_volatility) or benchmark_volatility <= 0.0:
            raise ValueError("previous-fold benchmark volatility must be finite and positive")
        scale = strategy_volatility / benchmark_volatility
        if not math.isfinite(scale) or scale < 0.0:
            raise ValueError("prior-fold volatility scale must be finite and non-negative")
        scales[current_fold] = scale
        current["prior_fold_scale"] = scale
        pieces.append(current)
    scaled = pd.concat(pieces, ignore_index=True)
    scaled["scaled_benchmark_position"] = scaled["benchmark_position"] * scaled["prior_fold_scale"]
    if bool((scaled["scaled_benchmark_position"] < 0.0).any()) or bool(
        (scaled["scaled_benchmark_position"] > MAX_POSITION + 1e-12).any()
    ):
        raise ValueError("scaled benchmark position must remain inside the long/cash bounds")
    turnover = scaled["scaled_benchmark_position"].diff().abs()
    turnover.iloc[0] = abs(float(scaled["scaled_benchmark_position"].iloc[0]))
    scaled["scaled_benchmark_turnover"] = turnover
    scaled["scaled_benchmark_trading_cost"] = turnover * TRANSACTION_COST_BPS / 10_000.0
    scaled["scaled_benchmark_return"] = (
        scaled["scaled_benchmark_position"] * scaled["asset_return"]
        - scaled["scaled_benchmark_trading_cost"]
    )
    return scaled, scales


def expected_shortfall(values: np.ndarray | pd.Series) -> float:
    array = np.asarray(values, dtype=float)
    if array.ndim != 1 or len(array) == 0 or not np.isfinite(array).all():
        raise ValueError("expected-shortfall input must be a non-empty finite vector")
    tail_count = math.ceil(TAIL_FRACTION * len(array))
    return float(np.sort(array)[:tail_count].mean())


def sampled_fold_sequence(
    folds: list[int], rng: np.random.Generator, *, block_length: int = FOLD_BLOCK_LENGTH
) -> list[int]:
    if block_length <= 0 or block_length > len(folds):
        raise ValueError("fold block length must be in [1, number of folds]")
    starts = np.arange(0, len(folds) - block_length + 1)
    sampled: list[int] = []
    while len(sampled) < len(folds):
        start = int(rng.choice(starts))
        sampled.extend(folds[start : start + block_length])
    return sampled[: len(folds)]


def analyze_market(
    frame: pd.DataFrame,
    benchmark: pd.DataFrame,
    market: str,
    reconstruction_error: float,
) -> dict[str, Any]:
    scaled, scales = prior_fold_scaled_returns(frame, benchmark)
    evaluation_folds = sorted(scales)
    strategy_es = expected_shortfall(scaled[STRATEGY_COLUMN])
    benchmark_es = expected_shortfall(scaled["scaled_benchmark_return"])
    delta = strategy_es - benchmark_es
    rng = np.random.default_rng(SEEDS[market])
    bootstrap_deltas = np.empty(RESAMPLES, dtype=float)
    by_fold = {fold: scaled.loc[scaled[FOLD_COLUMN] == fold] for fold in evaluation_folds}
    for index in range(RESAMPLES):
        sampled_folds = sampled_fold_sequence(evaluation_folds, rng)
        sample = pd.concat([by_fold[fold] for fold in sampled_folds], ignore_index=True)
        bootstrap_deltas[index] = expected_shortfall(sample[STRATEGY_COLUMN]) - expected_shortfall(
            sample["scaled_benchmark_return"]
        )
    alpha = (1.0 - CONFIDENCE) / 2.0
    lower, upper = np.quantile(bootstrap_deltas, [alpha, 1.0 - alpha])
    return {
        "market": market,
        "evaluation_observations": len(scaled),
        "evaluation_folds": evaluation_folds,
        "excluded_folds": [min(evaluation_folds) - 1, max(evaluation_folds) + 1],
        "prior_fold_scale_min": min(scales.values()),
        "prior_fold_scale_max": max(scales.values()),
        "prior_fold_scale_mean": float(np.mean(list(scales.values()))),
        "benchmark_reconstruction_max_abs_error": reconstruction_error,
        "scaled_benchmark_total_turnover": float(scaled["scaled_benchmark_turnover"].sum()),
        "scaled_benchmark_max_position": float(scaled["scaled_benchmark_position"].max()),
        "strategy_expected_shortfall": strategy_es,
        "scaled_benchmark_expected_shortfall": benchmark_es,
        "delta": delta,
        "confidence_interval": {"lower": float(lower), "upper": float(upper)},
        "probability_delta_positive": float(np.mean(bootstrap_deltas > 0.0)),
        "passes": bool(lower > 0.0),
    }


def build_result(artifact_dir: str | Path) -> dict[str, Any]:
    root = Path(artifact_dir)
    markets: dict[str, Any] = {}
    for market in MARKETS:
        returns_path = root / market / "walk_forward_returns.csv"
        snapshot_path = root / market / "snapshot" / f"okx-{market}-1Dutc.csv"
        frame = load_returns(returns_path, market)
        snapshot = load_snapshot(snapshot_path, market)
        benchmark, reconstruction_error = reconstruct_volatility_benchmark(snapshot, frame)
        result = analyze_market(frame, benchmark, market, reconstruction_error)
        result["return_file_sha256"] = file_sha256(returns_path)
        result["snapshot_file_sha256"] = file_sha256(snapshot_path)
        markets[market] = result
    passes = all(result["passes"] for result in markets.values())
    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "BTC-USDT and ETH-USDT strategy returns have less severe 5% expected "
            "shortfall than volatility-targeted long when each current fold's benchmark "
            "position is scaled using only the immediately preceding complete fold's "
            "realised volatility ratio and execution costs are recomputed."
        ),
        "method": {
            "tail_fraction": TAIL_FRACTION,
            "complete_fold_size": COMPLETE_FOLD_SIZE,
            "scaling": (
                "current fold reconstructed benchmark position multiplied by prior complete "
                "fold strategy-volatility / benchmark-volatility"
            ),
            "benchmark_reconstruction": (
                "30-session log-return volatility, 50% annual target, one-bar delay, "
                "long/cash cap 1, 10 bps turnover cost"
            ),
            "scaled_execution": (
                "turnover and costs recomputed from the scaled position with continuous fold "
                "boundaries and cash entry at evaluation start"
            ),
            "volatility": "sample standard deviation, ddof=1",
            "first_complete_fold": "used only to estimate fold-2 scale",
            "trailing_short_fold": "excluded",
            "fold_block_length": FOLD_BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "seeds": SEEDS,
        },
        "candidate_accounting": {
            "searched": 1,
            "passed": 1 if passes else 0,
            "rejected": 0 if passes else 1,
        },
        "verdict": "supported" if passes else "rejected",
        "failure_reasons": [
            f"{market} lower confidence bound was not positive"
            for market, result in markets.items()
            if not result["passes"]
        ],
        "source": {
            **SOURCE,
            "return_file_sha256": EXPECTED_RETURN_FILE_SHA256,
            "snapshot_file_sha256": EXPECTED_SNAPSHOT_FILE_SHA256,
        },
        "markets": markets,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_result(args.artifact_dir)
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
