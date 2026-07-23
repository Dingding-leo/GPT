from __future__ import annotations

import argparse
import hashlib
import json
import math
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
STRATEGY_RETURN_COLUMN = "strategy_return"
BENCHMARK_RETURN_COLUMN = "benchmark_volatility_targeted_long_return"
EXPECTED_RETURN_FILE_SHA256 = {
    "BTC-USDT": "ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce",
    "ETH-USDT": "bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047",
}
TAIL_FRACTION = 0.05
BLOCK_LENGTH = 20
RESAMPLES = 2_000
CONFIDENCE = 0.95
SEEDS = {"BTC-USDT": 2026072325, "ETH-USDT": 2026072326}
CANONICAL_SIGNATURE = (
    "volatility-matched-expected-shortfall-vs-volatility-benchmark-v1|"
    "markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns|"
    "benchmark=volatility-targeted-long-scaled-per-sample-to-strategy-sample-volatility|"
    "volatility=sample-standard-deviation-ddof1|"
    "metric=mean-worst-ceil-5pct-returns|tail-fraction=0.05|"
    "claim=strategy-minus-volatility-matched-benchmark-expected-shortfall>0-"
    "in-both-markets|resampling=paired-noncircular-moving-block-bootstrap|"
    "volatility-scale-recomputed-per-resample=true|block-length=20-sessions|"
    "resamples=2000|confidence=0.95|"
    "seeds=BTC-USDT:2026072325,ETH-USDT:2026072326|candidate_count=1"
)


def verify_return_payload_sha256(payload: bytes, market: str) -> str:
    if not isinstance(payload, bytes):
        raise TypeError("return payload must be bytes")
    try:
        expected = EXPECTED_RETURN_FILE_SHA256[market]
    except KeyError as exc:
        raise ValueError(f"unsupported market: {market}") from exc

    observed = hashlib.sha256(payload).hexdigest()
    if observed != expected:
        raise ValueError(
            f"{market} return file SHA-256 mismatch: expected {expected}, observed {observed}"
        )
    return observed


def read_verified_return_payloads(
    artifact_dir: str | Path,
) -> tuple[dict[str, bytes], dict[str, str]]:
    artifact_root = Path(artifact_dir)
    payloads = {
        market: (artifact_root / market / "walk_forward_returns.csv").read_bytes()
        for market in MARKETS
    }
    digests = {
        market: verify_return_payload_sha256(payloads[market], market) for market in MARKETS
    }
    return payloads, digests


def _validated_timestamps(values: pd.Series) -> pd.DatetimeIndex:
    raw = values.astype("string")
    explicit_zone = raw.str.contains(r"(?:Z|[+-]\d{2}:?\d{2})$", regex=True, na=False)
    if not bool(explicit_zone.all()):
        raise ValueError("timestamps must include an explicit timezone offset")

    timestamps = pd.DatetimeIndex(pd.to_datetime(raw, utc=True, errors="raise"))
    if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if len(timestamps) > 1:
        intervals = timestamps[1:] - timestamps[:-1]
        if not bool((intervals == pd.Timedelta(days=1)).all()):
            raise ValueError("timestamps must have exact daily cadence")
    return timestamps


def load_returns(payload: bytes) -> pd.DataFrame:
    if not isinstance(payload, bytes):
        raise TypeError("return payload must be bytes")
    frame = pd.read_csv(BytesIO(payload))
    required = {"timestamp", STRATEGY_RETURN_COLUMN, BENCHMARK_RETURN_COLUMN}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"returns file is missing required columns: {sorted(missing)}")

    validated = pd.DataFrame({"timestamp": _validated_timestamps(frame["timestamp"])})
    for column in (STRATEGY_RETURN_COLUMN, BENCHMARK_RETURN_COLUMN):
        values = pd.to_numeric(frame[column], errors="raise").to_numpy(dtype=float)
        if not np.isfinite(values).all() or np.any(values <= -1.0):
            raise ValueError(f"{column} must contain finite returns greater than -100%")
        validated[column] = values
    return validated


def expected_shortfall(returns: np.ndarray, tail_fraction: float) -> float:
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or values.size < 1:
        raise ValueError("returns must be a non-empty one-dimensional array")
    if not np.isfinite(values).all() or np.any(values <= -1.0):
        raise ValueError("returns must be finite and greater than -100%")
    if not isinstance(tail_fraction, (int, float)) or isinstance(tail_fraction, bool):
        raise ValueError("tail_fraction must be a real number")
    if not math.isfinite(float(tail_fraction)) or not 0.0 < float(tail_fraction) < 1.0:
        raise ValueError("tail_fraction must be finite and strictly between zero and one")

    tail_count = math.ceil(values.size * float(tail_fraction))
    return float(np.mean(np.partition(values, tail_count - 1)[:tail_count]))


def volatility_match_scale(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if strategy.shape != benchmark.shape:
        raise ValueError("strategy and benchmark returns must have identical shapes")
    if strategy.ndim != 1 or strategy.size < 2:
        raise ValueError("paired returns must contain at least two observations")
    if not np.isfinite(strategy).all() or not np.isfinite(benchmark).all():
        raise ValueError("paired returns must be finite")

    strategy_volatility = float(np.std(strategy, ddof=1))
    benchmark_volatility = float(np.std(benchmark, ddof=1))
    if not math.isfinite(strategy_volatility) or not math.isfinite(benchmark_volatility):
        raise ValueError("sample volatility must be finite")
    if benchmark_volatility <= 0.0:
        raise ValueError("benchmark sample volatility must be positive")
    return strategy_volatility / benchmark_volatility


def volatility_matched_expected_shortfall_delta(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    tail_fraction: float,
) -> dict[str, float]:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    scale = volatility_match_scale(strategy, benchmark)
    matched_benchmark = benchmark * scale
    strategy_es = expected_shortfall(strategy, tail_fraction)
    benchmark_es = expected_shortfall(matched_benchmark, tail_fraction)
    return {
        "volatility_match_scale": scale,
        "strategy_expected_shortfall": strategy_es,
        "volatility_matched_benchmark_expected_shortfall": benchmark_es,
        "observed_delta": strategy_es - benchmark_es,
    }


def moving_block_indices(
    observation_count: int,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if observation_count < 1:
        raise ValueError("observation_count must be positive")
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


def bootstrap_volatility_matched_expected_shortfall_delta(
    strategy_returns: np.ndarray,
    benchmark_returns: np.ndarray,
    *,
    tail_fraction: float,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, float]:
    strategy = np.asarray(strategy_returns, dtype=float)
    benchmark = np.asarray(benchmark_returns, dtype=float)
    if strategy.shape != benchmark.shape:
        raise ValueError("strategy and benchmark returns must have identical shapes")
    if strategy.ndim != 1 or strategy.size < 2:
        raise ValueError("paired returns must contain at least two observations")
    if not np.isfinite(strategy).all() or not np.isfinite(benchmark).all():
        raise ValueError("paired returns must be finite")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resamples must be a positive integer")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        raise ValueError("confidence must be a real number")
    if not math.isfinite(float(confidence)) or not 0.0 < float(confidence) < 1.0:
        raise ValueError("confidence must be finite and strictly between zero and one")

    observed = volatility_matched_expected_shortfall_delta(
        strategy,
        benchmark,
        tail_fraction=tail_fraction,
    )

    rng = np.random.default_rng(seed)
    deltas = np.empty(resamples, dtype=float)
    scales = np.empty(resamples, dtype=float)
    for index in range(resamples):
        sample_indices = moving_block_indices(strategy.size, block_length, rng)
        sample = volatility_matched_expected_shortfall_delta(
            strategy[sample_indices],
            benchmark[sample_indices],
            tail_fraction=tail_fraction,
        )
        deltas[index] = sample["observed_delta"]
        scales[index] = sample["volatility_match_scale"]

    alpha = 1.0 - float(confidence)
    lower, upper = np.quantile(deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    scale_lower, scale_upper = np.quantile(
        scales,
        [alpha / 2.0, 1.0 - alpha / 2.0],
    )
    return {
        **observed,
        "ci_lower": float(lower),
        "ci_upper": float(upper),
        "probability_delta_positive": float(np.mean(deltas > 0.0)),
        "bootstrap_scale_ci_lower": float(scale_lower),
        "bootstrap_scale_ci_upper": float(scale_upper),
    }


def analyze_market(
    payload: bytes,
    market: str,
    return_file_sha256: str,
) -> dict[str, object]:
    returns = load_returns(payload)
    result = bootstrap_volatility_matched_expected_shortfall_delta(
        returns[STRATEGY_RETURN_COLUMN].to_numpy(dtype=float),
        returns[BENCHMARK_RETURN_COLUMN].to_numpy(dtype=float),
        tail_fraction=TAIL_FRACTION,
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        confidence=CONFIDENCE,
        seed=SEEDS[market],
    )
    result["observations"] = len(returns)
    result["tail_observations"] = math.ceil(len(returns) * TAIL_FRACTION)
    result["period_start"] = returns["timestamp"].iloc[0].isoformat()
    result["period_end"] = returns["timestamp"].iloc[-1].isoformat()
    result["return_file_sha256"] = return_file_sha256
    result["passed"] = bool(result["ci_lower"] > 0.0)
    return result


def build_result(artifact_dir: str | Path) -> dict[str, object]:
    payloads, return_file_sha256 = read_verified_return_payloads(artifact_dir)
    markets = {
        market: analyze_market(payloads[market], market, return_file_sha256[market])
        for market in MARKETS
    }
    joint_passed = all(bool(markets[market]["passed"]) for market in MARKETS)
    failed_markets = [market for market in MARKETS if not bool(markets[market]["passed"])]
    rejection_reason = None
    if failed_markets:
        rejection_reason = (
            "The 95% paired moving-block-bootstrap lower bound for the strategy-minus-"
            "volatility-matched-volatility-targeted-long expected-shortfall delta was "
            "non-positive in: " + ", ".join(failed_markets)
        )

    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "The adaptive strategy has less severe 5% expected shortfall than the "
            "volatility-targeted-long benchmark after that benchmark is scaled to the "
            "strategy's sample volatility in both BTC-USDT and ETH-USDT."
        ),
        "candidate_accounting": {
            "searched": 1,
            "passed": int(joint_passed),
            "rejected": int(not joint_passed),
        },
        "settings": {
            "benchmark": "volatility-targeted long scaled to strategy sample volatility",
            "volatility_definition": "sample standard deviation with ddof=1",
            "volatility_scale_recomputed_per_resample": True,
            "expected_shortfall_definition": "mean of worst ceil(tail_fraction * n) returns",
            "tail_fraction": TAIL_FRACTION,
            "block_length_sessions": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "seeds": SEEDS,
        },
        "markets": markets,
        "verdict": "supported" if joint_passed else "rejected",
        "rejection_reason": rejection_reason,
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29996094865,
            "source_artifact_id": 8559031387,
            "source_artifact_name": "quant-research-source-1839-attempt-1",
            "source_artifact_sha256": (
                "9d7f5c91ac46c8a3d5a3b0d34f569936bd70bc4197161ae5d977c2c6730e0c04"
            ),
            "source_code_commit": "d2d569ee2e20d4fc4172e5339a2aa06862d66ea8",
            "source_main_base": "d1433f4e423861b953736f812f76cf24ac00de89",
            "merged_main_commit": "7928c12f53d0d4f8149ed9d5c4205eaa2ba072f5",
            "expected_return_file_sha256": EXPECTED_RETURN_FILE_SHA256,
            "development_markets": list(MARKETS),
        },
        "claim_scope": (
            "Development-market tail-shape diagnostic only; a rejected result means the "
            "unscaled expected-shortfall reduction versus volatility-targeted long is not "
            "shown to survive simple sample-volatility matching."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = build_result(args.artifact_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
