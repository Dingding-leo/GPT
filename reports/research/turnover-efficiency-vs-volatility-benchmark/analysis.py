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
STRATEGY_TURNOVER_COLUMN = "turnover"
BENCHMARK_RETURN_COLUMN = "benchmark_volatility_targeted_long_return"
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072311, "ETH-USDT": 2026072312}
VOLATILITY_LOOKBACK = 30
TARGET_VOLATILITY = 0.50
MAX_POSITION = 1.0
ANNUALIZATION = 365
TRANSACTION_COST_BPS = 10.0
BENCHMARK_MATCH_TOLERANCE = 5e-15
CANONICAL_SIGNATURE = (
    "turnover-efficiency-vs-volatility-benchmark-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns-and-turnover-plus-immutable-snapshot|"
    "benchmark=volatility-targeted-long-reconstructed-from-snapshot|"
    "metric=net-arithmetic-return-sum/absolute-position-turnover-sum|"
    "claim=strategy-minus-benchmark-return-per-turnover>0-in-both-markets|"
    "resampling=paired-four-column-noncircular-moving-block-bootstrap|"
    "block-length=20-sessions|resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072311,ETH-USDT:2026072312|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_timestamps(values: pd.Series, *, label: str) -> pd.DatetimeIndex:
    timestamps = pd.DatetimeIndex(pd.to_datetime(values, utc=True, errors="raise"))
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
        STRATEGY_TURNOVER_COLUMN,
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

    turnover = pd.to_numeric(frame[STRATEGY_TURNOVER_COLUMN], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(turnover).all() or np.any(turnover < 0.0):
        raise ValueError(f"{STRATEGY_TURNOVER_COLUMN} must be finite and non-negative")
    validated[STRATEGY_TURNOVER_COLUMN] = turnover
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
    target = (
        (TARGET_VOLATILITY / realized_volatility.replace(0.0, np.nan))
        .clip(0.0, MAX_POSITION)
        .shift(1)
        .fillna(0.0)
    )
    asset_return = prices.pct_change().fillna(0.0)
    turnover = target.diff().abs().fillna(target.abs())
    trading_cost = turnover * TRANSACTION_COST_BPS / 10_000.0
    benchmark_return = target * asset_return - trading_cost

    frame = pd.DataFrame(
        {
            "position": target,
            "turnover": turnover,
            "benchmark_return": benchmark_return,
        }
    ).loc[start:end]
    if frame.empty:
        raise ValueError("requested benchmark window is empty")

    first = frame.index[0]
    entry_turnover = abs(float(frame.at[first, "position"]))
    frame.at[first, "turnover"] = entry_turnover
    frame.at[first, "benchmark_return"] = (
        float(frame.at[first, "position"]) * float(asset_return.loc[first])
        - entry_turnover * TRANSACTION_COST_BPS / 10_000.0
    )
    return frame


def return_per_turnover(returns: np.ndarray, turnover: np.ndarray) -> float:
    return_values = np.asarray(returns, dtype=float)
    turnover_values = np.asarray(turnover, dtype=float)
    if return_values.shape != turnover_values.shape:
        raise ValueError("returns and turnover must have identical shapes")
    if return_values.ndim != 1 or return_values.size < 2:
        raise ValueError("returns and turnover must be one-dimensional with at least two values")
    if not np.isfinite(return_values).all() or np.any(return_values <= -1.0):
        raise ValueError("returns must be finite and greater than -100%")
    if not np.isfinite(turnover_values).all() or np.any(turnover_values < 0.0):
        raise ValueError("turnover must be finite and non-negative")

    total_turnover = float(np.sum(turnover_values))
    if total_turnover <= 0.0:
        raise ValueError("total turnover must be positive")
    return float(np.sum(return_values) / total_turnover)


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


def bootstrap_efficiency_delta(
    strategy_returns: np.ndarray,
    strategy_turnover: np.ndarray,
    benchmark_returns: np.ndarray,
    benchmark_turnover: np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float]:
    arrays = [
        np.asarray(strategy_returns, dtype=float),
        np.asarray(strategy_turnover, dtype=float),
        np.asarray(benchmark_returns, dtype=float),
        np.asarray(benchmark_turnover, dtype=float),
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

    strategy_efficiency = return_per_turnover(arrays[0], arrays[1])
    benchmark_efficiency = return_per_turnover(arrays[2], arrays[3])
    observed_delta = strategy_efficiency - benchmark_efficiency

    rng = np.random.default_rng(seed)
    deltas = np.empty(resamples, dtype=float)
    for index in range(resamples):
        sample_indices = moving_block_indices(arrays[0].size, block_length, rng)
        deltas[index] = return_per_turnover(
            arrays[0][sample_indices], arrays[1][sample_indices]
        ) - return_per_turnover(arrays[2][sample_indices], arrays[3][sample_indices])

    alpha = 1.0 - float(confidence)
    lower, upper = np.quantile(deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    return {
        "strategy_total_net_arithmetic_return": float(np.sum(arrays[0])),
        "strategy_total_turnover": float(np.sum(arrays[1])),
        "strategy_return_per_turnover": strategy_efficiency,
        "benchmark_total_net_arithmetic_return": float(np.sum(arrays[2])),
        "benchmark_total_turnover": float(np.sum(arrays[3])),
        "benchmark_return_per_turnover": benchmark_efficiency,
        "observed_delta": observed_delta,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "probability_delta_positive": float(np.mean(deltas > 0.0)),
    }


def analyze_market(artifact_dir: str | Path, market: str) -> dict[str, object]:
    root = Path(artifact_dir) / market
    returns_path = root / "walk_forward_returns.csv"
    snapshot_path = root / "snapshot" / f"okx-{market}-1Dutc.csv"
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

    result = bootstrap_efficiency_delta(
        returns[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float),
        returns[STRATEGY_TURNOVER_COLUMN].to_numpy(dtype=float),
        reconstructed_benchmark,
        benchmark["turnover"].to_numpy(dtype=float),
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
            "net return per unit turnover was non-positive in: " + ", ".join(failed_markets)
        )

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "The adaptive strategy has higher net arithmetic return per unit of absolute "
            "position turnover than volatility-targeted long in both BTC-USDT and ETH-USDT."
        ),
        "candidate_accounting": {
            "searched": 1,
            "passed": int(joint_passed),
            "rejected": int(not joint_passed),
        },
        "settings": {
            "block_length_sessions": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "benchmark": "volatility-targeted-long",
            "return_per_turnover_definition": (
                "sum(net daily arithmetic returns) / sum(absolute position turnover)"
            ),
            "reduction_definition": "strategy_return_per_turnover - benchmark_return_per_turnover",
            "benchmark_reconstruction": {
                "volatility_lookback": VOLATILITY_LOOKBACK,
                "target_volatility": TARGET_VOLATILITY,
                "max_position": MAX_POSITION,
                "annualization": ANNUALIZATION,
                "transaction_cost_bps": TRANSACTION_COST_BPS,
                "execution_delay_sessions": 1,
                "evaluation_entry_state": "cash",
                "persisted_return_match_tolerance": BENCHMARK_MATCH_TOLERANCE,
            },
            "seeds": SEEDS,
        },
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run": 29953609625,
            "source_artifact_id": 8543136580,
            "source_artifact_name": "quant-research-source-1333-attempt-1",
            "source_artifact_sha256": (
                "88f5457a66e756384386a9f9712b029bcefbb2335f881f17a75200180b071414"
            ),
            "source_head_sha": "4c484bddb670ca58c131ff55fbf1b176389abe62",
            "development_markets": list(MARKETS),
        },
        "markets": markets,
        "verdict": "passed" if joint_passed else "rejected",
        "rejection_reason": rejection_reason,
        "claim_scope": (
            "Development-market execution-efficiency diagnostic only; no alpha, capacity, or "
            "deployable strategy improvement is claimed."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = build_result(args.artifact_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
