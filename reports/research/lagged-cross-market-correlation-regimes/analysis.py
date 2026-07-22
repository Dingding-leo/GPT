from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

MARKETS = ("BTC-USDT", "ETH-USDT")
REGIMES = ("above_prior_median", "below_prior_median")
RETURN_FILE_SHA256 = {
    "BTC-USDT": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
    "ETH-USDT": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
}
CANONICAL_SIGNATURE = (
    "lagged-cross-market-correlation-regime-consistency-v1|"
    "markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-asset-and-strategy-returns|"
    "regime-statistic=btc-eth-pearson-correlation-of-asset-return-shift1-rolling60|"
    "threshold=expanding-median-of-prior-correlation-values-min60-shift1|"
    "regimes=above-or-equal-prior-median,below-prior-median|"
    "metric=conditional-annualized-arithmetic-mean-net-return|"
    "annualization=365|"
    "resampling=paired-four-column-noncircular-moving-block-with-regimes-recomputed|"
    "block=20|resamples=2000|confidence=0.95|seed=20260722|candidate_count=1"
)


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_aligned_returns(artifact_dir: str | Path) -> pd.DataFrame:
    root = Path(artifact_dir)
    market_frames: dict[str, pd.DataFrame] = {}
    for market in MARKETS:
        source = root / market / "walk_forward_returns.csv"
        actual_sha256 = file_sha256(source)
        expected_sha256 = RETURN_FILE_SHA256[market]
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f"{market} return file hash mismatch: expected {expected_sha256}, "
                f"actual {actual_sha256}"
            )
        frame = pd.read_csv(source)
        required = {"timestamp", "asset_return", "strategy_return"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{market} return file is missing columns: {sorted(missing)}")
        timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
        if timestamps.duplicated().any() or not timestamps.is_monotonic_increasing:
            raise ValueError(f"{market} timestamps must be unique and increasing")
        if len(timestamps) > 1:
            later = timestamps.iloc[1:].reset_index(drop=True)
            earlier = timestamps.iloc[:-1].reset_index(drop=True)
            intervals = later - earlier
            if not bool((intervals == pd.Timedelta(days=1)).all()):
                raise ValueError(f"{market} timestamps must have exact daily cadence")
        selected = frame[["asset_return", "strategy_return"]].apply(pd.to_numeric, errors="raise")
        if not np.isfinite(selected.to_numpy(dtype=float)).all():
            raise ValueError(f"{market} returns must be finite")
        selected.index = pd.DatetimeIndex(timestamps)
        selected.columns = [
            f"{market}_asset_return",
            f"{market}_strategy_return",
        ]
        market_frames[market] = selected

    btc = market_frames["BTC-USDT"]
    eth = market_frames["ETH-USDT"]
    if not btc.index.equals(eth.index):
        raise ValueError("BTC-USDT and ETH-USDT timestamps must match exactly")
    aligned = pd.concat([btc, eth], axis=1)
    if len(aligned) != 2340:
        raise ValueError(f"expected 2340 aligned observations, found {len(aligned)}")
    return aligned


def lagged_correlation_regimes(
    frame: pd.DataFrame,
    *,
    lookback: int = 60,
    minimum_correlation_history: int = 60,
) -> pd.DataFrame:
    if lookback < 2 or minimum_correlation_history < 2:
        raise ValueError("correlation lookback and history must both be at least 2")
    lagged_btc = frame["BTC-USDT_asset_return"].shift(1)
    lagged_eth = frame["ETH-USDT_asset_return"].shift(1)
    correlation = lagged_btc.rolling(lookback, min_periods=lookback).corr(lagged_eth)
    prior_median = correlation.expanding(min_periods=minimum_correlation_history).median().shift(1)
    eligible = correlation.notna() & prior_median.notna()
    labels = pd.Series(pd.NA, index=frame.index, dtype="string", name="regime")
    labels.loc[eligible & correlation.ge(prior_median)] = "above_prior_median"
    labels.loc[eligible & correlation.lt(prior_median)] = "below_prior_median"
    return pd.DataFrame(
        {
            "lagged_correlation": correlation,
            "prior_expanding_median": prior_median,
            "regime": labels,
        },
        index=frame.index,
    )


def conditional_annualized_means(
    frame: pd.DataFrame,
    labels: pd.Series,
    *,
    annualization: int = 365,
) -> dict[str, dict[str, float]]:
    output: dict[str, dict[str, float]] = {}
    for market in MARKETS:
        returns = frame[f"{market}_strategy_return"]
        output[market] = {
            regime: float(returns.loc[labels.eq(regime)].mean() * annualization)
            for regime in REGIMES
        }
    return output


def moving_block_indices(
    observation_count: int,
    *,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if block_length < 1 or block_length > observation_count:
        raise ValueError("block_length must be between 1 and the observation count")
    block_count = int(np.ceil(observation_count / block_length))
    starts = rng.integers(0, observation_count - block_length + 1, size=block_count)
    offsets = np.arange(block_length)
    return (starts[:, None] + offsets).reshape(-1)[:observation_count]


def bootstrap_conditional_means(
    frame: pd.DataFrame,
    *,
    lookback: int,
    minimum_correlation_history: int,
    annualization: int,
    block_length: int,
    resamples: int,
    seed: int,
) -> dict[str, dict[str, list[float]]]:
    if resamples < 1:
        raise ValueError("resamples must be positive")
    rng = np.random.default_rng(seed)
    values = frame.to_numpy(dtype=float)
    distributions = {market: {regime: [] for regime in REGIMES} for market in MARKETS}
    for _ in range(resamples):
        indices = moving_block_indices(len(frame), block_length=block_length, rng=rng)
        sampled = pd.DataFrame(values[indices], columns=frame.columns)
        regime_frame = lagged_correlation_regimes(
            sampled,
            lookback=lookback,
            minimum_correlation_history=minimum_correlation_history,
        )
        estimates = conditional_annualized_means(
            sampled,
            regime_frame["regime"],
            annualization=annualization,
        )
        for market in MARKETS:
            for regime in REGIMES:
                value = estimates[market][regime]
                if not np.isfinite(value):
                    raise RuntimeError("a bootstrap sample produced an empty regime")
                distributions[market][regime].append(value)
    return distributions


def summarize_distribution(
    values: Sequence[float],
    *,
    confidence: float,
) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    alpha = 1.0 - confidence
    return {
        "lower": float(np.quantile(array, alpha / 2.0)),
        "median": float(np.median(array)),
        "upper": float(np.quantile(array, 1.0 - alpha / 2.0)),
        "probability_positive": float(np.mean(array > 0.0)),
    }


def build_result(artifact_dir: str | Path) -> dict[str, Any]:
    lookback = 60
    minimum_correlation_history = 60
    annualization = 365
    block_length = 20
    resamples = 2000
    confidence = 0.95
    seed = 20260722

    frame = load_aligned_returns(artifact_dir)
    regime_frame = lagged_correlation_regimes(
        frame,
        lookback=lookback,
        minimum_correlation_history=minimum_correlation_history,
    )
    labels = regime_frame["regime"]
    point_estimates = conditional_annualized_means(frame, labels, annualization=annualization)
    distributions = bootstrap_conditional_means(
        frame,
        lookback=lookback,
        minimum_correlation_history=minimum_correlation_history,
        annualization=annualization,
        block_length=block_length,
        resamples=resamples,
        seed=seed,
    )

    market_results: dict[str, dict[str, Any]] = {}
    failed_conditions: list[str] = []
    for market in MARKETS:
        regime_results: dict[str, Any] = {}
        for regime in REGIMES:
            summary = summarize_distribution(distributions[market][regime], confidence=confidence)
            passed = summary["lower"] > 0.0
            if not passed:
                failed_conditions.append(
                    f"{market} {regime} lower confidence bound is not positive"
                )
            regime_results[regime] = {
                "observations": int(labels.eq(regime).sum()),
                "annualized_mean": point_estimates[market][regime],
                "confidence_interval": {
                    "confidence": confidence,
                    "lower": summary["lower"],
                    "upper": summary["upper"],
                },
                "bootstrap_median": summary["median"],
                "probability_positive": summary["probability_positive"],
                "passes": passed,
            }
        market_results[market] = regime_results

    verdict = "supported" if not failed_conditions else "rejected"
    return {
        "canonical_signature": CANONICAL_SIGNATURE,
        "hypothesis": (
            "For both BTC-USDT and ETH-USDT, persisted net rolling OOS returns have "
            "a positive annualized arithmetic mean when prior 60-session cross-market "
            "correlation is above or below its prior expanding median."
        ),
        "candidate_accounting": {
            "candidates_searched": 1,
            "candidates_passed": int(verdict == "supported"),
            "candidates_rejected": int(verdict == "rejected"),
            "failure_reasons": failed_conditions,
        },
        "method": {
            "markets": list(MARKETS),
            "annualization": annualization,
            "correlation_lookback_sessions": lookback,
            "minimum_prior_correlation_observations": minimum_correlation_history,
            "correlation_inputs": "asset returns shifted by one session",
            "threshold": "expanding median of earlier lagged rolling correlations",
            "threshold_shift_sessions": 1,
            "regimes": list(REGIMES),
            "moving_block_length": block_length,
            "resamples": resamples,
            "confidence": confidence,
            "seed": seed,
        },
        "data_summary": {
            "observations_per_market": len(frame),
            "eligible_observations": int(labels.notna().sum()),
            "warmup_observations": int(labels.isna().sum()),
            "start": frame.index[0].isoformat(),
            "end": frame.index[-1].isoformat(),
            "regime_observations": {regime: int(labels.eq(regime).sum()) for regime in REGIMES},
        },
        "results": market_results,
        "verdict": verdict,
        "claim_boundary": (
            "Rejected development-market diagnostic; no trading rule, alpha, or "
            "strategy improvement is claimed."
        ),
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": 29898899644,
            "source_artifact_id": 8521103926,
            "source_artifact_name": "quant-research-source-705-attempt-1",
            "source_artifact_sha256": (
                "d67057e47b8c466d2e3628283779785e662636cc4d631bb140be86cb5cf4c6ae"
            ),
            "source_branch": "auto/research/20260722-16-lagged-market-trend-regimes",
            "source_head_sha": "7945375b2f322390e0945a69c35d9f5217405f4e",
            "source_base_sha": "fc2100fa5ae4f815828960326405e7d171d59891",
            "source_checkout_sha": "cadd23dde47d235d549056b5459c51ea4cdf8e9f",
            "return_file_sha256": RETURN_FILE_SHA256,
        },
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "Moving-block concatenation creates artificial joins; correlation regimes are "
            "recomputed after resampling to prevent labels from crossing unchanged.",
            "The experiment does not model spread, market impact, liquidity, capacity, "
            "latency, or partial fills.",
        ],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test lagged cross-market correlation regime consistency."
    )
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = build_result(args.artifact_dir)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"verdict={result['verdict']}")
    print(f"candidate_count={result['candidate_accounting']['candidates_searched']}")
    print(f"output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
