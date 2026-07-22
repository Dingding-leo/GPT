from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 365
SKEWNESS_LOOKBACK = 60
BLOCK_LENGTH = 20
RESAMPLES = 2000
CONFIDENCE = 0.95
EXPECTED_CANDIDATE_COUNT = 27
EXPECTED_OBSERVATIONS = 2340
EXPECTED_SNAPSHOT_OBSERVATIONS = 3114
SELECTION_BARS = 730
TEST_BARS = 90
SOURCE_WORKFLOW_RUN_ID = 29910622011
SOURCE_ARTIFACT_ID = 8525728688
SOURCE_ARTIFACT_NAME = "quant-research-source-875-attempt-1"
SOURCE_ARTIFACT_SHA256 = "cc313c8d00910bcaea869c75c32ce4c4c62794b4d2362d9ac01c5dff63fb6327"
SOURCE_CODE_COMMIT = "b0de1618e26855228789ea7af15a7ef0e62d522f"
MARKETS = {
    "BTC-USDT": {
        "seed": 20260722,
        "snapshot_sha256": "b0bd7c6c7e30fcc095073169f60bde24559f481b24cc6f4bdfb85349f57974bb",
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "3627839318ff92086cf45ab460499fba64d1a3a9ae4198e941d4181f0d0825fe",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "snapshot_sha256": "78f3bf81d3983e6c894066a1c298fbf14ae06a5eff9ca7326554b0a8933c0df5",
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "569c23d3e78dbdc20014a9e3376874f7ec85a4679aa10d548bbb2ad75ba1093b",
    },
}
SIGNATURE = (
    "lagged-asset-return-skewness-regime-consistency-v1|"
    "markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns-and-OKX-close|"
    "regime-statistic=fisher-pearson-adjusted-skewness-of-prior-60-asset-returns|"
    "current-session-excluded=true|threshold=zero|regimes=positive,nonpositive|"
    "metric=conditional-annualized-arithmetic-mean-net-return|annualization=365|"
    "resampling=paired-noncircular-moving-block-over-observed-regime-return-rows|"
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
    if settings["non_overlapping_test_folds"] is not True:
        raise ValueError("walk-forward report must declare non-overlapping test folds")
    base_config = settings["base_config"]
    if not isinstance(base_config, dict):
        raise ValueError("walk-forward report base configuration must be a mapping")
    if base_config["annualization"] != ANNUALIZATION:
        raise ValueError("walk-forward report annualization changed")
    if base_config["transaction_cost_bps"] != 10.0:
        raise ValueError("walk-forward report transaction cost changed")


def lagged_return_skewness(
    close: pd.Series,
    *,
    lookback: int = SKEWNESS_LOOKBACK,
) -> pd.Series:
    """Adjusted sample skewness of asset returns known before each evaluated session."""

    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 3:
        raise ValueError("skewness lookback must be an integer of at least three")
    numeric = pd.to_numeric(close, errors="raise").astype(float)
    values = numeric.to_numpy()
    if numeric.isna().any() or not np.isfinite(values).all() or (values <= 0.0).any():
        raise ValueError("close values must be finite and positive")
    asset_return = numeric.pct_change(fill_method=None)
    return asset_return.shift(1).rolling(lookback, min_periods=lookback).skew()


def load_market_inputs(
    artifact_dir: Path,
    *,
    market: str,
    expected_snapshot_sha256: str,
    expected_returns_sha256: str,
    expected_report_sha256: str,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, object]]]:
    market_dir = artifact_dir / market
    snapshot_path = market_dir / "snapshot" / f"okx-{market}-1Dutc.csv"
    returns_path = market_dir / "walk_forward_returns.csv"
    report_path = market_dir / "walk_forward.json"
    for path, expected in {
        snapshot_path: expected_snapshot_sha256,
        returns_path: expected_returns_sha256,
        report_path: expected_report_sha256,
    }.items():
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"{path.name} hash mismatch: expected {expected}, actual {actual}")

    snapshot = pd.read_csv(snapshot_path)
    if {"timestamp", "close"} - set(snapshot):
        raise ValueError("snapshot is missing timestamp or close")
    if len(snapshot) != EXPECTED_SNAPSHOT_OBSERVATIONS:
        raise ValueError(
            f"snapshot must contain exactly {EXPECTED_SNAPSHOT_OBSERVATIONS} observations"
        )
    snapshot_index = explicit_daily_utc_index(snapshot["timestamp"], label="snapshot")
    closes = pd.to_numeric(snapshot["close"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(closes).all() or (closes <= 0.0).any():
        raise ValueError("snapshot closes must be finite and positive")
    snapshot_frame = pd.DataFrame({"close": closes}, index=snapshot_index)
    snapshot_frame["lagged_skewness"] = lagged_return_skewness(snapshot_frame["close"])

    returns = pd.read_csv(returns_path)
    missing = {"timestamp", "strategy_return", "fold"} - set(returns)
    if missing:
        raise ValueError(f"return file is missing required columns: {sorted(missing)}")
    if len(returns) != EXPECTED_OBSERVATIONS:
        raise ValueError(f"return file must contain exactly {EXPECTED_OBSERVATIONS} observations")
    returns_index = explicit_daily_utc_index(returns["timestamp"], label="return")
    strategy_returns = pd.to_numeric(returns["strategy_return"], errors="raise").to_numpy(
        dtype=float
    )
    folds = pd.to_numeric(returns["fold"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(strategy_returns).all() or (strategy_returns <= -1.0).any():
        raise ValueError("strategy returns must be finite and greater than -100%")
    if not np.isfinite(folds).all() or not np.equal(folds, np.floor(folds)).all():
        raise ValueError("fold identifiers must be finite integers")
    returns_frame = pd.DataFrame(
        {"strategy_return": strategy_returns, "fold": folds.astype(int)},
        index=returns_index,
    )

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
    return snapshot_frame, returns_frame, fold_reports


def classify_skewness_regimes(
    snapshot: pd.DataFrame,
    returns_frame: pd.DataFrame,
    fold_reports: list[dict[str, object]],
    *,
    test_bars: int = TEST_BARS,
) -> pd.DataFrame:
    if isinstance(test_bars, bool) or not isinstance(test_bars, int) or test_bars < 1:
        raise ValueError("test_bars must be a positive integer")
    if "lagged_skewness" not in snapshot or "strategy_return" not in returns_frame:
        raise ValueError("required skewness or strategy-return column is missing")

    classified_parts: list[pd.DataFrame] = []
    for fold_report in fold_reports:
        fold_id = int(fold_report["fold"])
        fold_frame = returns_frame.loc[returns_frame["fold"] == fold_id].copy()
        if len(fold_frame) != test_bars:
            raise ValueError(f"fold {fold_id} must contain exactly {test_bars} observations")
        if fold_frame.index[0].isoformat() != pd.Timestamp(fold_report["test_start"]).isoformat():
            raise ValueError(f"fold {fold_id} start does not match its report")
        if fold_frame.index[-1].isoformat() != pd.Timestamp(fold_report["test_end"]).isoformat():
            raise ValueError(f"fold {fold_id} end does not match its report")

        skewness = snapshot["lagged_skewness"].reindex(fold_frame.index)
        if skewness.isna().any():
            raise ValueError(f"fold {fold_id} test skewness is incomplete")
        fold_frame["lagged_skewness"] = skewness.to_numpy(dtype=float)
        fold_frame["regime"] = np.where(
            fold_frame["lagged_skewness"].to_numpy(dtype=float) > 0.0,
            "positive",
            "nonpositive",
        )
        classified_parts.append(fold_frame)

    classified = pd.concat(classified_parts).sort_index()
    if not classified.index.equals(returns_frame.index):
        raise ValueError("classified rows must preserve the complete return index")
    if set(classified["regime"]) != {"positive", "nonpositive"}:
        raise ValueError("classified rows must contain both skewness regimes")
    return classified


def moving_block_indices(n: int, *, block_length: int, resamples: int, seed: int) -> np.ndarray:
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError("observation count must be a positive integer")
    if isinstance(block_length, bool) or not isinstance(block_length, int) or block_length < 1:
        raise ValueError("block length must be a positive integer")
    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples < 1:
        raise ValueError("resample count must be a positive integer")
    if n < block_length:
        raise ValueError("block length cannot exceed the observation count")
    rng = np.random.default_rng(seed)
    blocks_per_sample = math.ceil(n / block_length)
    starts = rng.integers(0, n - block_length + 1, size=(resamples, blocks_per_sample))
    offsets = np.arange(block_length)
    indices = starts[..., None] + offsets
    return indices.reshape(resamples, -1)[:, :n]


def conditional_annualized_means(frame: pd.DataFrame) -> dict[str, float]:
    means: dict[str, float] = {}
    for regime in ("positive", "nonpositive"):
        values = frame.loc[frame["regime"] == regime, "strategy_return"].to_numpy(dtype=float)
        if not len(values):
            raise ValueError(f"sample contains no {regime} skewness observations")
        means[regime] = float(values.mean() * ANNUALIZATION)
    return means


def analyze_market(
    snapshot: pd.DataFrame,
    returns_frame: pd.DataFrame,
    fold_reports: list[dict[str, object]],
    *,
    seed: int,
) -> dict[str, object]:
    classified = classify_skewness_regimes(snapshot, returns_frame, fold_reports)
    point = conditional_annualized_means(classified)
    indices = moving_block_indices(
        len(classified),
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        seed=seed,
    )
    distributions = {"positive": np.empty(RESAMPLES), "nonpositive": np.empty(RESAMPLES)}
    for sample_index, row_indices in enumerate(indices):
        sampled = classified.iloc[row_indices]
        sample_means = conditional_annualized_means(sampled)
        for regime in distributions:
            distributions[regime][sample_index] = sample_means[regime]

    alpha = (1.0 - CONFIDENCE) / 2.0
    regimes: dict[str, object] = {}
    for regime in ("positive", "nonpositive"):
        distribution = distributions[regime]
        lower, upper = np.quantile(distribution, [alpha, 1.0 - alpha])
        regimes[regime] = {
            "observations": int((classified["regime"] == regime).sum()),
            "annualized_arithmetic_mean": point[regime],
            "confidence_interval": {"lower": float(lower), "upper": float(upper)},
            "probability_mean_positive": float((distribution > 0.0).mean()),
            "passes": bool(lower > 0.0),
        }
    return {"regimes": regimes}


def build_result(artifact_dir: Path) -> dict[str, object]:
    market_results: dict[str, object] = {}
    for market, evidence in MARKETS.items():
        snapshot, returns_frame, fold_reports = load_market_inputs(
            artifact_dir,
            market=market,
            expected_snapshot_sha256=str(evidence["snapshot_sha256"]),
            expected_returns_sha256=str(evidence["returns_sha256"]),
            expected_report_sha256=str(evidence["report_sha256"]),
        )
        market_results[market] = analyze_market(
            snapshot,
            returns_frame,
            fold_reports,
            seed=int(evidence["seed"]),
        )

    pass_flags = [
        bool(regime["passes"])
        for market_result in market_results.values()
        for regime in market_result["regimes"].values()
    ]
    passes = all(pass_flags)
    failure_reason = (
        None if passes else "At least one market/regime 95% lower confidence bound is non-positive."
    )
    return {
        "hypothesis": (
            "BTC-USDT and ETH-USDT net rolling OOS returns have positive annualized "
            "arithmetic means in both positive and non-positive prior 60-session "
            "asset-return skewness regimes."
        ),
        "canonical_signature": SIGNATURE,
        "candidate_accounting": {
            "searched": 1,
            "passed": int(passes),
            "rejected": int(not passes),
        },
        "verdict": "supported" if passes else "rejected",
        "failure_reason": failure_reason,
        "method": {
            "annualization": ANNUALIZATION,
            "skewness_lookback": SKEWNESS_LOOKBACK,
            "skewness_estimator": "Fisher-Pearson adjusted sample skewness (pandas rolling skew)",
            "current_session_excluded": True,
            "regime_threshold": 0.0,
            "regimes": ["positive", "nonpositive"],
            "block_length": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "candidate_count": 1,
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
            "source_code_commit": SOURCE_CODE_COMMIT,
            "oos_observations_per_market": EXPECTED_OBSERVATIONS,
            "oos_start": "2020-01-11T00:00:00+00:00",
            "oos_end": "2026-06-07T00:00:00+00:00",
            "markets": MARKETS,
        },
        "markets": market_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test conditional OOS means across lagged asset-return skewness regimes."
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_result(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"verdict={result['verdict']}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
