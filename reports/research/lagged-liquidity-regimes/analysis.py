from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 365
LIQUIDITY_LOOKBACK = 30
SELECTION_BARS = 730
TEST_BARS = 90
BLOCK_LENGTH = 20
RESAMPLES = 2000
CONFIDENCE = 0.95
EXPECTED_CANDIDATE_COUNT = 27
EXPECTED_OBSERVATIONS = 2340
SOURCE_WORKFLOW_RUN_ID = 29904635219
SOURCE_ARTIFACT_ID = 8523312240
SOURCE_ARTIFACT_NAME = "quant-research-source-780-attempt-1"
SOURCE_ARTIFACT_SHA256 = "5e8578dcc2aed7edbbc30b02b25cdb62ef7c01614305afeb09a940184c8d70a4"
SOURCE_CODE_COMMIT = "b383df39c2df12f5f11f059b8a2a2c463061f8e3"
MARKETS = {
    "BTC-USDT": {
        "seed": 20260722,
        "snapshot_sha256": "b0bd7c6c7e30fcc095073169f60bde24559f481b24cc6f4bdfb85349f57974bb",
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "93f5e00a3252bae08c3b5ee3f66036df36cc061a965c152dbfdfee3f523d20c4",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "snapshot_sha256": "78f3bf81d3983e6c894066a1c298fbf14ae06a5eff9ca7326554b0a8933c0df5",
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "bd46b5f17470b8680155e2659575fad5ffcc623da751ab51982ad347cd0a2f0e",
    },
}
SIGNATURE = (
    "selection-window-lagged-liquidity-regime-consistency-v1|"
    "markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns-and-OKX-volume_quote|"
    "liquidity=prior-30-session-median-volume_quote|"
    "threshold=median-of-lagged-liquidity-in-each-prior-730-session-selection-window|"
    "regimes=at-or-above-threshold,below-threshold|"
    "metric=conditional-annualized-arithmetic-mean-net-return|annualization=365|"
    "resampling=paired-noncircular-moving-block-over-regime-return-rows|"
    "block=20|resamples=2000|confidence=0.95|"
    "seeds=BTC:20260722,ETH:20260723|candidate_count=1"
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
    if index.duplicated().any() or not index.is_monotonic_increasing:
        raise ValueError(f"{label} timestamps must be unique and strictly increasing")
    if len(index) > 1:
        intervals = index[1:] - index[:-1]
        if not bool((intervals == pd.Timedelta(days=1)).all()):
            raise ValueError(f"{label} timestamps must have exact daily cadence")
    return index


def _validate_report(report: dict[str, object]) -> None:
    settings = report["settings"]
    if not isinstance(settings, dict):
        raise ValueError("walk-forward report settings must be a mapping")
    if settings["candidate_count"] != EXPECTED_CANDIDATE_COUNT:
        raise ValueError("walk-forward report candidate count changed")
    if settings["selection_bars"] != SELECTION_BARS:
        raise ValueError("walk-forward report selection length changed")
    if settings["test_bars"] != TEST_BARS:
        raise ValueError("walk-forward report test length changed")
    base_config = settings["base_config"]
    if not isinstance(base_config, dict):
        raise ValueError("walk-forward report base configuration must be a mapping")
    if base_config["annualization"] != ANNUALIZATION:
        raise ValueError("walk-forward report annualization changed")
    if base_config["transaction_cost_bps"] != 10.0:
        raise ValueError("walk-forward report transaction cost changed")
    if settings["non_overlapping_test_folds"] is not True:
        raise ValueError("walk-forward report must declare non-overlapping test folds")


def load_market_inputs(
    artifact_dir: Path,
    *,
    market: str,
    expected_snapshot_sha256: str,
    expected_returns_sha256: str,
    expected_report_sha256: str,
) -> tuple[pd.Series, pd.DataFrame]:
    market_dir = artifact_dir / market
    snapshot_path = market_dir / "snapshot" / f"okx-{market}-1Dutc.csv"
    returns_path = market_dir / "walk_forward_returns.csv"
    report_path = market_dir / "walk_forward.json"
    expected_hashes = {
        snapshot_path: expected_snapshot_sha256,
        returns_path: expected_returns_sha256,
        report_path: expected_report_sha256,
    }
    for path, expected in expected_hashes.items():
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"{path.name} hash mismatch: expected {expected}, actual {actual}")

    snapshot = pd.read_csv(snapshot_path)
    returns = pd.read_csv(returns_path)
    missing_snapshot = {"timestamp", "volume_quote", "confirm"} - set(snapshot)
    missing_returns = {"timestamp", "fold", "strategy_return"} - set(returns)
    if missing_snapshot:
        raise ValueError(f"snapshot is missing required columns: {sorted(missing_snapshot)}")
    if missing_returns:
        raise ValueError(f"return file is missing required columns: {sorted(missing_returns)}")
    if len(returns) != EXPECTED_OBSERVATIONS:
        raise ValueError(f"return file must contain exactly {EXPECTED_OBSERVATIONS} observations")

    snapshot_index = explicit_daily_utc_index(snapshot["timestamp"], label="snapshot")
    return_index = explicit_daily_utc_index(returns["timestamp"], label="return")
    volume = pd.to_numeric(snapshot["volume_quote"], errors="raise").to_numpy(dtype=float)
    confirmations = pd.to_numeric(snapshot["confirm"], errors="raise").to_numpy(dtype=float)
    strategy_returns = pd.to_numeric(
        returns["strategy_return"], errors="raise"
    ).to_numpy(dtype=float)
    numeric_folds = pd.to_numeric(returns["fold"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(volume).all() or (volume <= 0.0).any():
        raise ValueError("snapshot quote volume must be finite and positive")
    if not np.equal(confirmations, 1.0).all():
        raise ValueError("snapshot must contain confirmed candles only")
    if not np.isfinite(strategy_returns).all() or (strategy_returns <= -1.0).any():
        raise ValueError("strategy returns must be finite and greater than -100%")
    if (
        not np.isfinite(numeric_folds).all()
        or not np.equal(numeric_folds, np.floor(numeric_folds)).all()
    ):
        raise ValueError("fold identifiers must be finite integers")

    volume_series = pd.Series(volume, index=snapshot_index, name="volume_quote")
    returns_frame = pd.DataFrame(
        {
            "fold": numeric_folds.astype(int),
            "strategy_return": strategy_returns,
        },
        index=return_index,
    )
    if len(return_index.difference(snapshot_index)):
        raise ValueError("return timestamps must be present in the verified snapshot")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    _validate_report(report)
    fold_reports = report["folds"]
    if not isinstance(fold_reports, list):
        raise ValueError("walk-forward report folds must be a list")
    fold_ids = [int(fold["fold"]) for fold in fold_reports]
    if fold_ids != list(range(1, len(fold_ids) + 1)):
        raise ValueError("walk-forward fold identifiers must be consecutive from one")
    if sorted(returns_frame["fold"].unique().tolist()) != fold_ids:
        raise ValueError("return-file fold identifiers do not match the report")
    for fold_report in fold_reports:
        fold_id = int(fold_report["fold"])
        fold_frame = returns_frame.loc[returns_frame["fold"] == fold_id]
        if len(fold_frame) != TEST_BARS:
            raise ValueError(f"fold {fold_id} must contain exactly {TEST_BARS} observations")
        if fold_frame.index[0].isoformat() != pd.Timestamp(fold_report["test_start"]).isoformat():
            raise ValueError(f"fold {fold_id} start does not match its report")
        if fold_frame.index[-1].isoformat() != pd.Timestamp(fold_report["test_end"]).isoformat():
            raise ValueError(f"fold {fold_id} end does not match its report")
    return volume_series, returns_frame


def classify_liquidity_regimes(
    volume_quote: pd.Series,
    returns_frame: pd.DataFrame,
    *,
    liquidity_lookback: int = LIQUIDITY_LOOKBACK,
    selection_bars: int = SELECTION_BARS,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    if liquidity_lookback < 2 or selection_bars < liquidity_lookback:
        raise ValueError("liquidity lookback and selection window are inconsistent")
    if not isinstance(volume_quote.index, pd.DatetimeIndex):
        raise TypeError("quote volume must use a DatetimeIndex")
    if not isinstance(returns_frame.index, pd.DatetimeIndex):
        raise TypeError("return frame must use a DatetimeIndex")

    lagged_liquidity = (
        volume_quote.shift(1)
        .rolling(liquidity_lookback, min_periods=liquidity_lookback)
        .median()
    )
    classified = returns_frame.copy()
    classified["lagged_liquidity"] = lagged_liquidity.reindex(classified.index)
    classified["regime"] = pd.Series(index=classified.index, dtype="object")
    thresholds: list[dict[str, object]] = []
    minimum_valid_selection = selection_bars - liquidity_lookback

    for fold_id, fold_frame in classified.groupby("fold", sort=True):
        fold_start = fold_frame.index[0]
        selection_values = lagged_liquidity.loc[lagged_liquidity.index < fold_start].tail(
            selection_bars
        )
        valid_selection = selection_values.dropna()
        if len(selection_values) != selection_bars:
            raise ValueError(f"fold {fold_id} lacks its complete prior selection window")
        if len(valid_selection) < minimum_valid_selection:
            raise ValueError(f"fold {fold_id} lacks enough prior liquidity observations")
        threshold = float(valid_selection.median())
        fold_liquidity = classified.loc[fold_frame.index, "lagged_liquidity"]
        if fold_liquidity.isna().any():
            raise ValueError(f"fold {fold_id} has unavailable lagged liquidity")
        classified.loc[fold_frame.index, "regime"] = np.where(
            fold_liquidity.to_numpy(dtype=float) >= threshold,
            "high",
            "low",
        )
        thresholds.append(
            {
                "fold": int(fold_id),
                "test_start": fold_start.isoformat(),
                "selection_observations": len(selection_values),
                "valid_liquidity_observations": len(valid_selection),
                "threshold_volume_quote": threshold,
            }
        )

    if classified["regime"].isna().any():
        raise RuntimeError("every OOS observation must receive a liquidity regime")
    if set(classified["regime"]) != {"high", "low"}:
        raise ValueError("classified OOS rows must contain both liquidity regimes")
    return classified, thresholds


def moving_block_indices(n: int, *, block_length: int, resamples: int, seed: int) -> np.ndarray:
    if n < block_length:
        raise ValueError("block length cannot exceed the observation count")
    if block_length < 1 or resamples < 1:
        raise ValueError("block length and resample count must be positive")
    rng = np.random.default_rng(seed)
    blocks_per_sample = math.ceil(n / block_length)
    starts = rng.integers(0, n - block_length + 1, size=(resamples, blocks_per_sample))
    offsets = np.arange(block_length)
    indices = starts[..., None] + offsets
    return indices.reshape(resamples, -1)[:, :n]


def conditional_annualized_means(frame: pd.DataFrame) -> dict[str, float]:
    means: dict[str, float] = {}
    for regime in ("high", "low"):
        values = frame.loc[frame["regime"] == regime, "strategy_return"].to_numpy(dtype=float)
        if not len(values):
            raise ValueError(f"sample contains no {regime}-liquidity observations")
        means[regime] = float(values.mean() * ANNUALIZATION)
    return means


def analyze_market(
    volume_quote: pd.Series,
    returns_frame: pd.DataFrame,
    *,
    seed: int,
) -> dict[str, object]:
    classified, thresholds = classify_liquidity_regimes(volume_quote, returns_frame)
    point = conditional_annualized_means(classified)
    indices = moving_block_indices(
        len(classified),
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        seed=seed,
    )
    distributions = {"high": np.empty(RESAMPLES), "low": np.empty(RESAMPLES)}
    for sample_index, row_indices in enumerate(indices):
        sampled = classified.iloc[row_indices]
        sample_means = conditional_annualized_means(sampled)
        for regime in distributions:
            distributions[regime][sample_index] = sample_means[regime]

    alpha = (1.0 - CONFIDENCE) / 2.0
    regimes: dict[str, object] = {}
    for regime in ("high", "low"):
        distribution = distributions[regime]
        lower, upper = np.quantile(distribution, [alpha, 1.0 - alpha])
        observations = int((classified["regime"] == regime).sum())
        regimes[regime] = {
            "observations": observations,
            "annualized_arithmetic_mean": point[regime],
            "confidence_interval": {"lower": float(lower), "upper": float(upper)},
            "probability_mean_positive": float((distribution > 0.0).mean()),
            "passes": bool(lower > 0.0),
        }

    threshold_values = np.asarray(
        [threshold["threshold_volume_quote"] for threshold in thresholds], dtype=float
    )
    return {
        "observations": len(classified),
        "folds": len(thresholds),
        "seed": seed,
        "threshold_summary": {
            "minimum": float(threshold_values.min()),
            "median": float(np.median(threshold_values)),
            "maximum": float(threshold_values.max()),
            "first_fold_valid_selection_observations": int(
                thresholds[0]["valid_liquidity_observations"]
            ),
            "later_fold_valid_selection_observations": int(
                min(
                    threshold["valid_liquidity_observations"]
                    for threshold in thresholds[1:]
                )
            ),
        },
        "regimes": regimes,
        "passes": all(regime["passes"] for regime in regimes.values()),
    }


def build_result(artifact_dir: Path) -> dict[str, object]:
    market_results: dict[str, object] = {}
    failures: list[str] = []
    for market, specification in MARKETS.items():
        volume_quote, returns_frame = load_market_inputs(
            artifact_dir,
            market=market,
            expected_snapshot_sha256=specification["snapshot_sha256"],
            expected_returns_sha256=specification["returns_sha256"],
            expected_report_sha256=specification["report_sha256"],
        )
        result = analyze_market(volume_quote, returns_frame, seed=specification["seed"])
        market_results[market] = result
        for regime, regime_result in result["regimes"].items():
            if not regime_result["passes"]:
                failures.append(
                    f"{market} {regime}-liquidity mean 95% lower bound is non-positive: "
                    f"{regime_result['confidence_interval']['lower']:.12f}"
                )

    passed = not failures
    return {
        "canonical_signature": SIGNATURE,
        "candidate_count": 1,
        "candidates": [
            {
                "name": "selection-window-lagged-liquidity-regime-consistency",
                "verdict": "pass" if passed else "reject",
                "failure_reasons": failures,
            }
        ],
        "hypothesis": (
            "BTC-USDT and ETH-USDT net rolling OOS returns have positive annualized "
            "arithmetic means in both high and low prior quote-volume regimes."
        ),
        "economic_rationale": (
            "A credible daily strategy should not require only liquid, high-participation sessions "
            "or only quiet sessions. Each fold's regime threshold is fixed using its preceding "
            "selection window, so no test-fold volume informs the threshold."
        ),
        "method": {
            "annualization": ANNUALIZATION,
            "liquidity_field": "OKX volume_quote",
            "liquidity_statistic": "median of the prior 30 confirmed 1Dutc sessions",
            "threshold": (
                "median lagged-liquidity statistic in each fold's prior "
                "730-session selection window"
            ),
            "high_regime_rule": "lagged liquidity is greater than or equal to the fold threshold",
            "low_regime_rule": "lagged liquidity is below the fold threshold",
            "block_length_observations": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "resampling": (
                "paired non-circular moving blocks over observed regime and net-return rows"
            ),
            "acceptance_rule": "all four 95% lower bounds must be strictly positive",
        },
        "source": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "markets": list(MARKETS),
            "workflow_run_id": SOURCE_WORKFLOW_RUN_ID,
            "artifact_id": SOURCE_ARTIFACT_ID,
            "artifact_name": SOURCE_ARTIFACT_NAME,
            "artifact_sha256": SOURCE_ARTIFACT_SHA256,
            "code_commit": SOURCE_CODE_COMMIT,
            "snapshot_sha256": {
                market: specification["snapshot_sha256"]
                for market, specification in MARKETS.items()
            },
            "returns_sha256": {
                market: specification["returns_sha256"]
                for market, specification in MARKETS.items()
            },
            "report_sha256": {
                market: specification["report_sha256"]
                for market, specification in MARKETS.items()
            },
            "observations_per_market": EXPECTED_OBSERVATIONS,
            "oos_start": "2020-01-11T00:00:00+00:00",
            "oos_end": "2026-06-07T00:00:00+00:00",
            "development_markets": True,
        },
        "markets": market_results,
        "verdict": "supported" if passed else "rejected",
        "failure_reasons": failures,
        "limitations": [
            "BTC-USDT and ETH-USDT are development markets, not untouched holdouts.",
            "Quote volume is exchange-specific and can change with price level and venue activity.",
            "Moving-block concatenation introduces artificial joins between observed blocks.",
            "The analysis does not model spread, impact, capacity, latency, or partial fills.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test net-return consistency across lagged OKX quote-volume regimes."
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"candidate_count={result['candidate_count']}")
    print(f"verdict={result['verdict']}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
