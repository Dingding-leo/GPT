from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
STRATEGY_RETURN_COLUMN = "strategy_return"
STRATEGY_POSITION_COLUMN = "position"
BENCHMARK_RETURN_COLUMN = "benchmark_volatility_targeted_long_return"
ANNUALIZATION = 365
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072321, "ETH-USDT": 2026072322}
VOLATILITY_LOOKBACK = 30
TARGET_VOLATILITY = 0.50
MAX_POSITION = 1.0
TRANSACTION_COST_BPS = 10.0
BENCHMARK_MATCH_TOLERANCE = 5e-15
SOURCE_WORKFLOW_RUN_ID = 30006567781
SOURCE_ARTIFACT_ID = 8563252094
SOURCE_ARTIFACT_NAME = "quant-research-source-1960-attempt-1"
SOURCE_ARTIFACT_SHA256 = "e42b2b125328c945ace98c41c48a84d6b10d1876da03e20ee8fc3f25335e04e8"
SOURCE_WORKFLOW_HEAD_SHA = "8d5ca1d00aee75c3ef2303d62784d9c6fcfe5888"
SOURCE_MANIFEST_CODE_COMMIT = "72144e9f22dfeceda744d33222d3e0512e489a9d"
EXPECTED_RETURN_FILE_SHA256 = {
    "BTC-USDT": "ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce",
    "ETH-USDT": "bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047",
}
EXPECTED_SNAPSHOT_FILE_SHA256 = {
    "BTC-USDT": "407aeba3d1ad4c8e8682a6a689c1c6327139f42bc7587aaae75c77fce047dec1",
    "ETH-USDT": "842b4bbbb0ad7afbe2a1c9ee375443671d818a799266d5dc25cc6a548571ad7f",
}
CANONICAL_SIGNATURE = (
    "exposure-efficiency-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns-and-positions-plus-immutable-snapshot|"
    "benchmark=volatility-targeted-long-reconstructed-from-snapshot|"
    "metric=365*sum-net-arithmetic-return/sum-executed-position|"
    "claim=strategy-minus-benchmark-return-per-exposure-day>0-in-both-markets|"
    "resampling=paired-four-column-noncircular-moving-block-bootstrap|"
    "block-length=20-sessions|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072321,ETH-USDT:2026072322|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file_sha256(path: str | Path, expected: str, *, label: str) -> str:
    observed = file_sha256(path)
    if observed != expected:
        raise ValueError(f"{label} SHA-256 mismatch: expected {expected}, observed {observed}")
    return observed


def _validated_timestamps(values: pd.Series, *, label: str) -> pd.DatetimeIndex:
    raw = values.astype("string")
    explicit_zone = raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if not bool(explicit_zone.all()):
        raise ValueError(f"{label} timestamps must include an explicit timezone offset")
    timestamps = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError(f"{label} timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = timestamps[1:] - timestamps[:-1]
        if not bool((intervals == pd.Timedelta(days=1)).all()):
            raise ValueError(f"{label} timestamps must have exact daily cadence")
    return timestamps


def load_returns(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {
        "timestamp",
        STRATEGY_RETURN_COLUMN,
        STRATEGY_POSITION_COLUMN,
        BENCHMARK_RETURN_COLUMN,
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")

    validated = pd.DataFrame(
        {"timestamp": _validated_timestamps(frame["timestamp"], label="returns")}
    )
    for column in (STRATEGY_RETURN_COLUMN, BENCHMARK_RETURN_COLUMN):
        values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(values <= -1.0):
            raise ValueError(f"{column} must contain finite returns greater than -100%")
        validated[column] = values

    positions = pd.to_numeric(frame[STRATEGY_POSITION_COLUMN], errors="raise").to_numpy(
        dtype=float
    )
    if not np.isfinite(positions).all() or np.any((positions < 0.0) | (positions > 1.0)):
        raise ValueError(f"{STRATEGY_POSITION_COLUMN} must be finite and within [0, 1]")
    validated[STRATEGY_POSITION_COLUMN] = positions
    return validated


def reconstruct_volatility_targeted_long(
    snapshot_path: str | Path,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    snapshot = pd.read_csv(snapshot_path)
    required = {"timestamp", "close"}
    missing = required - set(snapshot.columns)
    if missing:
        raise ValueError(f"snapshot is missing required columns: {sorted(missing)}")

    timestamps = _validated_timestamps(snapshot["timestamp"], label="snapshot")
    closes = pd.to_numeric(snapshot["close"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(closes).all() or np.any(closes <= 0.0):
        raise ValueError("snapshot closes must be finite and positive")
    prices = pd.Series(closes, index=timestamps, name="close")

    log_returns = np.log(prices).diff()
    realized_volatility = log_returns.rolling(
        VOLATILITY_LOOKBACK,
        min_periods=VOLATILITY_LOOKBACK,
    ).std(ddof=0) * np.sqrt(ANNUALIZATION)
    position = (
        (TARGET_VOLATILITY / realized_volatility.replace(0.0, np.nan))
        .clip(0.0, MAX_POSITION)
        .shift(1)
        .fillna(0.0)
    )
    asset_return = prices.pct_change().fillna(0.0)
    turnover = position.diff().abs().fillna(position.abs())
    trading_cost = turnover * TRANSACTION_COST_BPS / 10_000.0
    benchmark_return = position * asset_return - trading_cost

    frame = pd.DataFrame(
        {
            "position": position,
            "benchmark_return": benchmark_return,
        }
    ).loc[start:end]
    if frame.empty:
        raise ValueError("requested benchmark window is empty")

    first = frame.index[0]
    entry_turnover = abs(float(frame.at[first, "position"]))
    frame.at[first, "benchmark_return"] = (
        float(frame.at[first, "position"]) * float(asset_return.loc[first])
        - entry_turnover * TRANSACTION_COST_BPS / 10_000.0
    )
    return frame


def annualized_return_per_exposure_day(returns: np.ndarray, positions: np.ndarray) -> float:
    return_values = np.asarray(returns, dtype=float)
    position_values = np.asarray(positions, dtype=float)
    if return_values.shape != position_values.shape:
        raise ValueError("returns and positions must have identical shapes")
    if return_values.ndim != 1 or return_values.size < 2:
        raise ValueError("returns and positions must be one-dimensional with at least two values")
    if not np.isfinite(return_values).all() or np.any(return_values <= -1.0):
        raise ValueError("returns must be finite and greater than -100%")
    if not np.isfinite(position_values).all() or np.any(
        (position_values < 0.0) | (position_values > 1.0)
    ):
        raise ValueError("positions must be finite and within [0, 1]")

    total_exposure_days = float(np.sum(position_values))
    if total_exposure_days <= 0.0:
        raise ValueError("total exposure-days must be positive")
    return float(ANNUALIZATION * np.sum(return_values) / total_exposure_days)


def moving_block_indices(
    observation_count: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if observation_count < 2:
        raise ValueError("observation_count must be at least 2")
    if isinstance(block_length, bool) or not isinstance(block_length, int):
        raise ValueError("block_length must be an integer")
    if block_length < 1 or block_length > observation_count:
        raise ValueError("block_length must be between 1 and observation_count")

    block_count = math.ceil(observation_count / block_length)
    starts = rng.integers(0, observation_count - block_length + 1, size=block_count)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observation_count]


def bootstrap_exposure_efficiency_delta(
    strategy_returns: np.ndarray,
    strategy_positions: np.ndarray,
    benchmark_returns: np.ndarray,
    benchmark_positions: np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float]:
    arrays = [
        np.asarray(strategy_returns, dtype=float),
        np.asarray(strategy_positions, dtype=float),
        np.asarray(benchmark_returns, dtype=float),
        np.asarray(benchmark_positions, dtype=float),
    ]
    if any(array.ndim != 1 for array in arrays):
        raise ValueError("paired inputs must be one-dimensional")
    if len({array.shape for array in arrays}) != 1 or arrays[0].size < 2:
        raise ValueError("paired inputs must have identical non-trivial shapes")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("confidence must be a real number")
    if not math.isfinite(float(confidence)) or not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be finite and strictly between zero and one")

    strategy_efficiency = annualized_return_per_exposure_day(arrays[0], arrays[1])
    benchmark_efficiency = annualized_return_per_exposure_day(arrays[2], arrays[3])
    observed_delta = strategy_efficiency - benchmark_efficiency

    rng = np.random.default_rng(seed)
    deltas = np.empty(resamples, dtype=float)
    for index in range(resamples):
        sample_indices = moving_block_indices(arrays[0].size, block_length, rng)
        deltas[index] = annualized_return_per_exposure_day(
            arrays[0][sample_indices], arrays[1][sample_indices]
        ) - annualized_return_per_exposure_day(
            arrays[2][sample_indices], arrays[3][sample_indices]
        )

    alpha = 1.0 - float(confidence)
    lower, upper = np.quantile(deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "strategy_total_net_arithmetic_return": float(np.sum(arrays[0])),
        "strategy_total_exposure_days": float(np.sum(arrays[1])),
        "strategy_average_exposure": float(np.mean(arrays[1])),
        "strategy_annualized_return_per_exposure_day": strategy_efficiency,
        "benchmark_total_net_arithmetic_return": float(np.sum(arrays[2])),
        "benchmark_total_exposure_days": float(np.sum(arrays[3])),
        "benchmark_average_exposure": float(np.mean(arrays[3])),
        "benchmark_annualized_return_per_exposure_day": benchmark_efficiency,
        "observed_delta": observed_delta,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "probability_delta_positive": float(np.mean(deltas > 0.0)),
    }


def analyze_market(artifact_dir: str | Path, market: str) -> dict[str, object]:
    root = Path(artifact_dir) / market
    returns_path = root / "walk_forward_returns.csv"
    snapshot_path = root / "snapshot" / f"okx-{market}-1Dutc.csv"
    verify_file_sha256(
        returns_path,
        EXPECTED_RETURN_FILE_SHA256[market],
        label=f"{market} return file",
    )
    verify_file_sha256(
        snapshot_path,
        EXPECTED_SNAPSHOT_FILE_SHA256[market],
        label=f"{market} snapshot file",
    )
    returns = load_returns(returns_path)
    benchmark = reconstruct_volatility_targeted_long(
        snapshot_path,
        start=returns["timestamp"].iloc[0],
        end=returns["timestamp"].iloc[-1],
    )
    if not benchmark.index.equals(pd.DatetimeIndex(returns["timestamp"])):
        raise ValueError("reconstructed benchmark timestamps do not match persisted OOS rows")

    persisted_benchmark = returns[BENCHMARK_RETURN_COLUMN].to_numpy(dtype=float)
    reconstructed_benchmark = benchmark["benchmark_return"].to_numpy(dtype=float)
    maximum_match_error = float(np.max(np.abs(persisted_benchmark - reconstructed_benchmark)))
    if maximum_match_error > BENCHMARK_MATCH_TOLERANCE:
        raise ValueError(
            "reconstructed benchmark returns do not match persisted returns within tolerance"
        )

    result = bootstrap_exposure_efficiency_delta(
        returns[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float),
        returns[STRATEGY_POSITION_COLUMN].to_numpy(dtype=float),
        reconstructed_benchmark,
        benchmark["position"].to_numpy(dtype=float),
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        confidence=CONFIDENCE,
        seed=SEEDS[market],
    )
    result["observations"] = len(returns)
    result["period_start"] = returns["timestamp"].iloc[0].isoformat()
    result["period_end"] = returns["timestamp"].iloc[-1].isoformat()
    result["return_file_sha256"] = file_sha256(returns_path)
    result["snapshot_file_sha256"] = file_sha256(snapshot_path)
    result["benchmark_return_maximum_reconstruction_error"] = maximum_match_error
    result["passed"] = bool(result["ci_lower"] > 0.0)
    return result


def build_result(artifact_dir: str | Path) -> dict[str, object]:
    markets = {market: analyze_market(artifact_dir, market) for market in MARKETS}
    joint_passed = all(bool(markets[market]["passed"]) for market in MARKETS)
    failed_markets = [market for market in MARKETS if not bool(markets[market]["passed"])]
    rejection_reason = None
    if failed_markets:
        rejection_reason = (
            "The 95% paired moving-block-bootstrap lower bound for strategy-minus-benchmark "
            "annualized net arithmetic return per exposure-day was non-positive in: "
            + ", ".join(failed_markets)
        )

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "The adaptive strategy has higher annualized net arithmetic return per executed "
            "exposure-day than volatility-targeted long in both BTC-USDT and ETH-USDT."
        ),
        "candidate_accounting": {
            "searched": 1,
            "passed": int(joint_passed),
            "rejected": int(not joint_passed),
        },
        "settings": {
            "annualization": ANNUALIZATION,
            "block_length_sessions": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "benchmark": "volatility-targeted-long",
            "metric_definition": (
                "365 * sum(net daily arithmetic returns) / sum(executed long exposure)"
            ),
            "delta_definition": "strategy exposure efficiency - benchmark exposure efficiency",
            "benchmark_reconstruction": {
                "volatility_lookback": VOLATILITY_LOOKBACK,
                "target_volatility": TARGET_VOLATILITY,
                "max_position": MAX_POSITION,
                "execution_delay_sessions": 1,
                "transaction_cost_bps": TRANSACTION_COST_BPS,
                "cash_entry_at_oos_start": True,
            },
            "seeds": SEEDS,
        },
        "source": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "workflow_run_id": SOURCE_WORKFLOW_RUN_ID,
            "artifact_id": SOURCE_ARTIFACT_ID,
            "artifact_name": SOURCE_ARTIFACT_NAME,
            "artifact_sha256": SOURCE_ARTIFACT_SHA256,
            "workflow_head_sha": SOURCE_WORKFLOW_HEAD_SHA,
            "manifest_code_commit": SOURCE_MANIFEST_CODE_COMMIT,
        },
        "markets": markets,
        "verdict": "supported" if joint_passed else "rejected",
        "rejection_reason": rejection_reason,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare net return per exposure-day with volatility-targeted long."
    )
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"verdict={result['verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
