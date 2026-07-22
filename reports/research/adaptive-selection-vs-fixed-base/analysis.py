from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ANNUALIZATION = 365
MOMENTUM_LOOKBACK = 90
REVERSAL_LOOKBACK = 5
TREND_WEIGHT = 0.70
VOLATILITY_LOOKBACK = 30
TARGET_VOLATILITY = 0.50
MAX_POSITION = 1.0
MIN_POSITION = 0.0
TRANSACTION_COST_BPS = 10.0
SELECTION_BARS = 730
TEST_BARS = 90
EXPECTED_OBSERVATIONS = 2340
BLOCK_LENGTH = 20
RESAMPLES = 2000
CONFIDENCE = 0.95
EVALUATION_START = pd.Timestamp("2020-01-11T00:00:00Z")
EVALUATION_END = pd.Timestamp("2026-06-07T00:00:00Z")
SOURCE_WORKFLOW_RUN_ID = 29918619194
SOURCE_ARTIFACT_ID = 8528966554
SOURCE_ARTIFACT_NAME = "quant-research-source-973-attempt-1"
SOURCE_ARTIFACT_SHA256 = "67bbf4136107a98bde8ddb118c6449d9db4da75b7eb7e9d3da82f822b156f43b"
SOURCE_HEAD_COMMIT = "007935d8581a6c1b622ce0a7702faaa0884cf227"
SOURCE_BASE_COMMIT = "762151882255be7b2e3bd26370151b8182526fd3"
MARKETS = {
    "BTC-USDT": {
        "seed": 202607223,
        "snapshot_sha256": "b0bd7c6c7e30fcc095073169f60bde24559f481b24cc6f4bdfb85349f57974bb",
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "b06a4cc4f059e4b0642d390d7cb19e105e4eb5875ef58f95d8f3a679a6168e14",
    },
    "ETH-USDT": {
        "seed": 202607224,
        "snapshot_sha256": "78f3bf81d3983e6c894066a1c298fbf14ae06a5eff9ca7326554b0a8933c0df5",
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "90364aceef3cb297704aa26e65e3c2cef6f3b02f11251184d9c3f7ade52787c8",
    },
}
SIGNATURE = (
    "adaptive-selection-vs-fixed-base-v1|markets=BTC-USDT,ETH-USDT|"
    "source=immutable-OKX-1Dutc-snapshots-and-persisted-net-rolling-oos-returns|"
    "adaptive=repository-730-selection-90-test-27-grid|"
    "fixed-base=momentum90-reversal5-trend0.70-vol30-targetvol0.50-long-cash|"
    "execution=one-bar-delay-10bps-continuous-position|"
    "evaluation=2020-01-11..2026-06-07-2340-bars|"
    "metrics=annualized-arithmetic-mean-delta,annualized-sharpe-delta|"
    "resampling=paired-noncircular-moving-block-bootstrap-20|resamples=2000|confidence=0.95|"
    "pass=both-metric-lower-bounds-positive-in-both-markets|candidate_count=1"
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def explicit_daily_utc_index(values: pd.Series, *, label: str) -> pd.DatetimeIndex:
    parsed: list[pd.Timestamp] = []
    for value in values:
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp) or timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f"{label} timestamps must contain explicit timezone information")
        parsed.append(timestamp)
    index = pd.DatetimeIndex(pd.to_datetime(parsed, utc=True))
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{label} timestamps must be unique and strictly increasing")
    if len(index) > 1 and not bool(((index[1:] - index[:-1]) == pd.Timedelta(days=1)).all()):
        raise ValueError(f"{label} timestamps must have exact daily cadence")
    return index


def target_position(prices: pd.Series) -> pd.Series:
    log_returns = np.log(prices).diff()
    trend_mean = log_returns.rolling(
        MOMENTUM_LOOKBACK,
        min_periods=MOMENTUM_LOOKBACK,
    ).mean()
    trend_std = log_returns.rolling(
        MOMENTUM_LOOKBACK,
        min_periods=MOMENTUM_LOOKBACK,
    ).std(ddof=0)
    trend_score = trend_mean / trend_std.replace(0.0, np.nan) * math.sqrt(MOMENTUM_LOOKBACK)
    recent_return = log_returns.rolling(
        REVERSAL_LOOKBACK,
        min_periods=REVERSAL_LOOKBACK,
    ).sum()
    risk_scale = log_returns.rolling(
        VOLATILITY_LOOKBACK,
        min_periods=VOLATILITY_LOOKBACK,
    ).std(ddof=0)
    reversal_score = -recent_return / (
        risk_scale.replace(0.0, np.nan) * math.sqrt(REVERSAL_LOOKBACK)
    )
    ensemble = (TREND_WEIGHT * trend_score + (1.0 - TREND_WEIGHT) * reversal_score).clip(-4.0, 4.0)
    directional = pd.Series(np.tanh(ensemble.to_numpy()), index=ensemble.index)
    realized_volatility = risk_scale * math.sqrt(ANNUALIZATION)
    volatility_scalar = (TARGET_VOLATILITY / realized_volatility.replace(0.0, np.nan)).clip(
        lower=0.0, upper=MAX_POSITION
    )
    return (
        (directional * volatility_scalar)
        .clip(MIN_POSITION, MAX_POSITION)
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
        .rename("target_position")
    )


def build_fixed_base_frame(prices: pd.Series) -> pd.DataFrame:
    target = target_position(prices)
    position = target.shift(1).fillna(0.0).rename("position")
    asset_return = prices.pct_change().fillna(0.0).rename("asset_return")
    turnover = position.diff().abs().fillna(position.abs()).rename("turnover")
    trading_cost = (turnover * TRANSACTION_COST_BPS / 10_000.0).rename("trading_cost")
    strategy_return = (position * asset_return - trading_cost).rename("strategy_return")
    return pd.concat(
        [position, turnover, trading_cost, strategy_return],
        axis=1,
    )


def annualized_mean(returns: np.ndarray) -> float:
    return float(np.mean(returns) * ANNUALIZATION)


def annualized_sharpe(returns: np.ndarray) -> float:
    standard_deviation = float(np.std(returns, ddof=0))
    if standard_deviation == 0.0:
        return 0.0
    return float(np.mean(returns) / standard_deviation * math.sqrt(ANNUALIZATION))


def moving_block_indices(
    observations: int,
    *,
    block_length: int,
    rng: np.random.Generator,
) -> np.ndarray:
    if isinstance(observations, bool) or not isinstance(observations, int) or observations < 2:
        raise ValueError("observations must be an integer of at least two")
    if isinstance(block_length, bool) or not isinstance(block_length, int):
        raise ValueError("block_length must be an integer")
    if not 2 <= block_length <= observations:
        raise ValueError("block_length must be between two and observations")
    block_count = math.ceil(observations / block_length)
    starts = rng.integers(0, observations - block_length + 1, size=block_count)
    indices = np.concatenate(
        [np.arange(start, start + block_length, dtype=int) for start in starts]
    )
    return indices[:observations]


def paired_bootstrap_comparison(
    adaptive_returns: np.ndarray,
    fixed_returns: np.ndarray,
    *,
    block_length: int,
    resamples: int,
    confidence: float,
    seed: int,
) -> dict[str, Any]:
    adaptive = np.asarray(adaptive_returns, dtype=float)
    fixed = np.asarray(fixed_returns, dtype=float)
    if adaptive.ndim != 1 or fixed.ndim != 1 or len(adaptive) != len(fixed):
        raise ValueError("paired returns must be one-dimensional with equal length")
    if len(adaptive) < 20 or not np.isfinite(adaptive).all() or not np.isfinite(fixed).all():
        raise ValueError("paired returns must contain at least 20 finite observations")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 100:
        raise ValueError("resamples must be an integer of at least 100")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be in (0, 1)")
    rng = np.random.default_rng(seed)
    mean_deltas = np.empty(resamples, dtype=float)
    sharpe_deltas = np.empty(resamples, dtype=float)
    for sample_index in range(resamples):
        indices = moving_block_indices(
            len(adaptive),
            block_length=block_length,
            rng=rng,
        )
        sampled_adaptive = adaptive[indices]
        sampled_fixed = fixed[indices]
        mean_deltas[sample_index] = annualized_mean(sampled_adaptive) - annualized_mean(
            sampled_fixed
        )
        sharpe_deltas[sample_index] = annualized_sharpe(sampled_adaptive) - annualized_sharpe(
            sampled_fixed
        )
    alpha = 1.0 - confidence
    mean_interval = np.quantile(mean_deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    sharpe_interval = np.quantile(sharpe_deltas, [alpha / 2.0, 1.0 - alpha / 2.0])
    point_mean_delta = annualized_mean(adaptive) - annualized_mean(fixed)
    point_sharpe_delta = annualized_sharpe(adaptive) - annualized_sharpe(fixed)
    passes = bool(mean_interval[0] > 0.0 and sharpe_interval[0] > 0.0)
    return {
        "observations": len(adaptive),
        "adaptive_annualized_mean": annualized_mean(adaptive),
        "fixed_annualized_mean": annualized_mean(fixed),
        "annualized_mean_delta": point_mean_delta,
        "annualized_mean_delta_interval": [float(value) for value in mean_interval],
        "probability_annualized_mean_delta_positive": float(np.mean(mean_deltas > 0.0)),
        "adaptive_annualized_sharpe": annualized_sharpe(adaptive),
        "fixed_annualized_sharpe": annualized_sharpe(fixed),
        "annualized_sharpe_delta": point_sharpe_delta,
        "annualized_sharpe_delta_interval": [float(value) for value in sharpe_interval],
        "probability_annualized_sharpe_delta_positive": float(np.mean(sharpe_deltas > 0.0)),
        "passes": passes,
    }


def load_market_inputs(
    artifact_dir: Path,
    market: str,
) -> tuple[pd.Series, dict[str, Any], pd.DataFrame]:
    evidence = MARKETS[market]
    market_dir = artifact_dir / market
    snapshot_path = market_dir / "snapshot" / f"okx-{market}-1Dutc.csv"
    report_path = market_dir / "walk_forward.json"
    returns_path = market_dir / "walk_forward_returns.csv"
    for path, expected in {
        snapshot_path: evidence["snapshot_sha256"],
        report_path: evidence["report_sha256"],
        returns_path: evidence["returns_sha256"],
    }.items():
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"{path.name} hash mismatch: expected {expected}, actual {actual}")
    snapshot = pd.read_csv(snapshot_path)
    if len(snapshot) != 3114:
        raise ValueError("snapshot observation count changed")
    snapshot_index = explicit_daily_utc_index(snapshot["timestamp"], label="snapshot")
    closes = pd.to_numeric(snapshot["close"], errors="raise").to_numpy(dtype=float)
    confirms = pd.to_numeric(snapshot["confirm"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(closes).all() or (closes <= 0.0).any() or not np.equal(confirms, 1.0).all():
        raise ValueError("snapshot must contain positive closes and only confirmed rows")
    prices = pd.Series(closes, index=snapshot_index, name="close")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    settings = report.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("walk-forward settings must be a mapping")
    expected_settings = {
        "candidate_count": 27,
        "selection_bars": SELECTION_BARS,
        "test_bars": TEST_BARS,
        "non_overlapping_test_folds": True,
    }
    for key, expected in expected_settings.items():
        if settings.get(key) != expected:
            raise ValueError(f"walk-forward setting {key} changed")
    base = settings.get("base_config")
    expected_base = {
        "annualization": ANNUALIZATION,
        "momentum_lookback": MOMENTUM_LOOKBACK,
        "reversal_lookback": REVERSAL_LOOKBACK,
        "trend_weight": TREND_WEIGHT,
        "reversal_weight": 1.0 - TREND_WEIGHT,
        "volatility_lookback": VOLATILITY_LOOKBACK,
        "target_volatility": TARGET_VOLATILITY,
        "max_abs_position": MAX_POSITION,
        "min_position": MIN_POSITION,
        "transaction_cost_bps": TRANSACTION_COST_BPS,
    }
    if not isinstance(base, dict):
        raise ValueError("walk-forward base configuration must be a mapping")
    for key, expected in expected_base.items():
        actual = base.get(key)
        if isinstance(expected, float):
            matches = isinstance(actual, (int, float)) and math.isclose(
                float(actual), expected, rel_tol=0.0, abs_tol=1e-12
            )
        else:
            matches = actual == expected
        if not matches:
            raise ValueError(f"walk-forward base configuration {key} changed")
    persisted = pd.read_csv(returns_path)
    persisted.index = explicit_daily_utc_index(persisted["timestamp"], label="return")
    if len(persisted) != EXPECTED_OBSERVATIONS:
        raise ValueError("walk-forward return observation count changed")
    if persisted.index[0] != EVALUATION_START or persisted.index[-1] != EVALUATION_END:
        raise ValueError("walk-forward evaluation boundary changed")
    return prices, report, persisted


def validate_selected_path_reproduction(
    prices: pd.Series,
    report: dict[str, Any],
    persisted: pd.DataFrame,
) -> float:
    previous_position = 0.0
    reconstructed: list[pd.DataFrame] = []
    for fold in report["folds"]:
        parameters = fold["selected_parameters"]
        momentum = int(parameters["momentum_lookback"])
        reversal = int(parameters["reversal_lookback"])
        trend_weight = float(parameters["trend_weight"])
        log_returns = np.log(prices).diff()
        trend_mean = log_returns.rolling(momentum, min_periods=momentum).mean()
        trend_std = log_returns.rolling(momentum, min_periods=momentum).std(ddof=0)
        trend_score = trend_mean / trend_std.replace(0.0, np.nan) * math.sqrt(momentum)
        recent_return = log_returns.rolling(reversal, min_periods=reversal).sum()
        risk_scale = log_returns.rolling(
            VOLATILITY_LOOKBACK,
            min_periods=VOLATILITY_LOOKBACK,
        ).std(ddof=0)
        reversal_score = -recent_return / (risk_scale.replace(0.0, np.nan) * math.sqrt(reversal))
        ensemble = (trend_weight * trend_score + (1.0 - trend_weight) * reversal_score).clip(
            -4.0, 4.0
        )
        directional = pd.Series(np.tanh(ensemble.to_numpy()), index=ensemble.index)
        realized_volatility = risk_scale * math.sqrt(ANNUALIZATION)
        volatility_scalar = (TARGET_VOLATILITY / realized_volatility.replace(0.0, np.nan)).clip(
            lower=0.0, upper=MAX_POSITION
        )
        target = (
            (directional * volatility_scalar)
            .clip(MIN_POSITION, MAX_POSITION)
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
        )
        position = target.shift(1).fillna(0.0)
        asset_return = prices.pct_change().fillna(0.0)
        turnover = position.diff().abs().fillna(position.abs())
        cost = turnover * TRANSACTION_COST_BPS / 10_000.0
        frame = pd.DataFrame(
            {
                "position": position,
                "turnover": turnover,
                "trading_cost": cost,
                "strategy_return": position * asset_return - cost,
            }
        ).loc[fold["test_start"] : fold["test_end"]]
        first = frame.index[0]
        first_turnover = abs(float(frame.at[first, "position"]) - previous_position)
        frame.at[first, "turnover"] = first_turnover
        frame.at[first, "trading_cost"] = first_turnover * TRANSACTION_COST_BPS / 10_000.0
        frame.at[first, "strategy_return"] = float(frame.at[first, "position"]) * float(
            asset_return.at[first]
        ) - float(frame.at[first, "trading_cost"])
        previous_position = float(frame["position"].iloc[-1])
        reconstructed.append(frame)
    combined = pd.concat(reconstructed)
    expected = pd.to_numeric(persisted["strategy_return"], errors="raise").to_numpy(dtype=float)
    actual = combined["strategy_return"].to_numpy(dtype=float)
    if not combined.index.equals(persisted.index):
        raise ValueError("reconstructed selected path index does not match persisted OOS returns")
    maximum_error = float(np.max(np.abs(actual - expected)))
    if maximum_error > 5e-15:
        raise ValueError(f"selected path reconstruction differs by {maximum_error}")
    return maximum_error


def build_result(artifact_dir: Path) -> dict[str, Any]:
    market_results: dict[str, Any] = {}
    for market, evidence in MARKETS.items():
        prices, report, persisted = load_market_inputs(artifact_dir, market)
        reproduction_error = validate_selected_path_reproduction(prices, report, persisted)
        fixed = build_fixed_base_frame(prices).loc[EVALUATION_START:EVALUATION_END]
        if len(fixed) != EXPECTED_OBSERVATIONS or not fixed.index.equals(persisted.index):
            raise ValueError(f"{market} fixed base path does not match the evaluation window")
        adaptive_returns = pd.to_numeric(
            persisted["strategy_return"],
            errors="raise",
        ).to_numpy(dtype=float)
        fixed_returns = fixed["strategy_return"].to_numpy(dtype=float)
        comparison = paired_bootstrap_comparison(
            adaptive_returns,
            fixed_returns,
            block_length=BLOCK_LENGTH,
            resamples=RESAMPLES,
            confidence=CONFIDENCE,
            seed=int(evidence["seed"]),
        )
        comparison["selected_path_reproduction_max_abs_error"] = reproduction_error
        market_results[market] = comparison
    passes = all(bool(result["passes"]) for result in market_results.values())
    return {
        "hypothesis": (
            "The repository's adaptive rolling parameter selection improves both annualized "
            "arithmetic mean net return and annualized Sharpe versus its fixed base "
            "configuration in BTC-USDT and ETH-USDT."
        ),
        "canonical_signature": SIGNATURE,
        "candidate_accounting": {
            "searched": 1,
            "passed": int(passes),
            "rejected": int(not passes),
        },
        "verdict": "supported" if passes else "rejected",
        "failure_reason": (
            None
            if passes
            else (
                "At least one market or metric has a non-positive 95% paired "
                "moving-block-bootstrap lower bound."
            )
        ),
        "method": {
            "adaptive_process": (
                "repository rolling 730-bar selection / 90-bar test over 27 candidates"
            ),
            "fixed_base_configuration": {
                "momentum_lookback": MOMENTUM_LOOKBACK,
                "reversal_lookback": REVERSAL_LOOKBACK,
                "trend_weight": TREND_WEIGHT,
                "reversal_weight": 1.0 - TREND_WEIGHT,
                "volatility_lookback": VOLATILITY_LOOKBACK,
                "target_volatility": TARGET_VOLATILITY,
                "min_position": MIN_POSITION,
                "max_position": MAX_POSITION,
            },
            "annualization": ANNUALIZATION,
            "transaction_cost_bps": TRANSACTION_COST_BPS,
            "execution_delay_bars": 1,
            "block_length": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "development_markets": True,
        },
        "provenance": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "source_workflow_run_id": SOURCE_WORKFLOW_RUN_ID,
            "source_artifact_id": SOURCE_ARTIFACT_ID,
            "source_artifact_name": SOURCE_ARTIFACT_NAME,
            "source_artifact_sha256": SOURCE_ARTIFACT_SHA256,
            "source_head_commit": SOURCE_HEAD_COMMIT,
            "source_base_commit": SOURCE_BASE_COMMIT,
            "oos_observations_per_market": EXPECTED_OBSERVATIONS,
            "oos_start": EVALUATION_START.isoformat(),
            "oos_end": EVALUATION_END.isoformat(),
            "markets": MARKETS,
        },
        "markets": market_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Compare adaptive rolling selection with the fixed repository base configuration."
        )
    )
    parser.add_argument("--artifact-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"verdict={result['verdict']}")
    for market, market_result in result["markets"].items():
        print(f"{market}_mean_delta={market_result['annualized_mean_delta']:.6f}")
        print(f"{market}_sharpe_delta={market_result['annualized_sharpe_delta']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
