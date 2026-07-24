from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

ANNUALIZATION = 365
DRAWDOWN_LOOKBACK = 60
BLOCK_LENGTH = 20
RESAMPLES = 2000
CONFIDENCE = 0.95
EXPECTED_CANDIDATE_COUNT = 27
EXPECTED_OBSERVATIONS = 2340
SELECTION_BARS = 730
TEST_BARS = 90
SOURCE_WORKFLOW_RUN_ID = 29908375375
SOURCE_ARTIFACT_ID = 8524820348
SOURCE_ARTIFACT_NAME = "quant-research-source-821-attempt-1"
SOURCE_ARTIFACT_SHA256 = "a3afb910142939e7d17d92c947957ea0b965b9411f057d96854fdccb96779401"
SOURCE_CODE_COMMIT = "513cdf4051f504ea7f833713911cd55ff7754881"
MARKETS = {
    "BTC-USDT": {
        "seed": 20260722,
        "snapshot_sha256": "b0bd7c6c7e30fcc095073169f60bde24559f481b24cc6f4bdfb85349f57974bb",
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "84fdba156cbd87b9f3bcd0be017039cdf9d3489bbb23333bd4961318c7bf9aad",
    },
    "ETH-USDT": {
        "seed": 20260723,
        "snapshot_sha256": "78f3bf81d3983e6c894066a1c298fbf14ae06a5eff9ca7326554b0a8933c0df5",
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "149e7ebf6f4192298828536d17685a09884da8ae699e0af22655bd6d5543f2bc",
    },
}
SIGNATURE = (
    "lagged-drawdown-state-consistency-v1|"
    "markets=BTC-USDT,ETH-USDT|source=persisted-net-rolling-oos-returns-and-OKX-close|"
    "regime-statistic=prior-60-session-close-drawdown-from-prior-60-session-high|"
    "current-session-excluded=true|"
    "threshold=zero|regimes=at-prior-60-session-high,underwater|"
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


def lagged_drawdown(close: pd.Series, *, lookback: int = DRAWDOWN_LOOKBACK) -> pd.Series:
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2:
        raise ValueError("drawdown lookback must be an integer of at least two")
    numeric = pd.to_numeric(close, errors="raise").astype(float)
    if numeric.isna().any() or not np.isfinite(numeric.to_numpy()).all() or (numeric <= 0.0).any():
        raise ValueError("close values must be finite and positive")
    prior_close = numeric.shift(1)
    prior_high = prior_close.rolling(lookback, min_periods=lookback).max()
    return prior_close / prior_high - 1.0


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
    snapshot_index = explicit_daily_utc_index(snapshot["timestamp"], label="snapshot")
    closes = pd.to_numeric(snapshot["close"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(closes).all() or (closes <= 0.0).any():
        raise ValueError("snapshot closes must be finite and positive")
    snapshot_frame = pd.DataFrame({"close": closes}, index=snapshot_index)
    snapshot_frame["lagged_drawdown"] = lagged_drawdown(snapshot_frame["close"])

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


def classify_drawdown_regimes(
    snapshot: pd.DataFrame,
    returns_frame: pd.DataFrame,
    fold_reports: list[dict[str, object]],
    *,
    test_bars: int = TEST_BARS,
) -> pd.DataFrame:
    if isinstance(test_bars, bool) or not isinstance(test_bars, int) or test_bars < 1:
        raise ValueError("test_bars must be a positive integer")
    if "lagged_drawdown" not in snapshot or "strategy_return" not in returns_frame:
        raise ValueError("required drawdown or strategy-return column is missing")

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

        drawdown = snapshot["lagged_drawdown"].reindex(fold_frame.index)
        if drawdown.isna().any():
            raise ValueError(f"fold {fold_id} test drawdown is incomplete")
        fold_frame["lagged_drawdown"] = drawdown.to_numpy(dtype=float)
        fold_frame["regime"] = np.where(
            np.isclose(fold_frame["lagged_drawdown"].to_numpy(dtype=float), 0.0, atol=1e-15),
            "at_high",
            "underwater",
        )
        classified_parts.append(fold_frame)

    classified = pd.concat(classified_parts).sort_index()
    if not classified.index.equals(returns_frame.index):
        raise ValueError("classified rows must preserve the complete return index")
    if set(classified["regime"]) != {"at_high", "underwater"}:
        raise ValueError("classified rows must contain both drawdown regimes")
    return classified


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
    for regime in ("at_high", "underwater"):
        values = frame.loc[frame["regime"] == regime, "strategy_return"].to_numpy(dtype=float)
        if not len(values):
            raise ValueError(f"sample contains no {regime} drawdown observations")
        means[regime] = float(values.mean() * ANNUALIZATION)
    return means


def analyze_market(
    snapshot: pd.DataFrame,
    returns_frame: pd.DataFrame,
    fold_reports: list[dict[str, object]],
    *,
    seed: int,
) -> dict[str, object]:
    classified = classify_drawdown_regimes(snapshot, returns_frame, fold_reports)
    point = conditional_annualized_means(classified)
    indices = moving_block_indices(
        len(classified),
        block_length=BLOCK_LENGTH,
        resamples=RESAMPLES,
        seed=seed,
    )
    distributions = {"at_high": np.empty(RESAMPLES), "underwater": np.empty(RESAMPLES)}
    for sample_index, row_indices in enumerate(indices):
        sampled = classified.iloc[row_indices]
        sample_means = conditional_annualized_means(sampled)
        for regime in distributions:
            distributions[regime][sample_index] = sample_means[regime]

    alpha = (1.0 - CONFIDENCE) / 2.0
    regimes: dict[str, object] = {}
    for regime in ("at_high", "underwater"):
        distribution = distributions[regime]
        lower, upper = np.quantile(distribution, [alpha, 1.0 - alpha])
        regimes[regime] = {
            "observations": int((classified["regime"] == regime).sum()),
            "annualized_arithmetic_mean": point[regime],
            "confidence_interval": {"lower": float(lower), "upper": float(upper)},
            "probability_mean_positive": float((distribution > 0.0).mean()),
            "passes": bool(lower > 0.0),
        }

    drawdown = classified["lagged_drawdown"].to_numpy(dtype=float)
    return {
        "observations": len(classified),
        "seed": seed,
        "regime_statistic_summary": {
            "minimum": float(drawdown.min()),
            "median": float(np.median(drawdown)),
            "maximum": float(drawdown.max()),
        },
        "regimes": regimes,
    }


def run_analysis(artifact_dir: Path) -> dict[str, object]:
    market_results: dict[str, object] = {}
    for market, settings in MARKETS.items():
        snapshot, returns_frame, fold_reports = load_market_inputs(
            artifact_dir,
            market=market,
            expected_snapshot_sha256=str(settings["snapshot_sha256"]),
            expected_returns_sha256=str(settings["returns_sha256"]),
            expected_report_sha256=str(settings["report_sha256"]),
        )
        market_results[market] = analyze_market(
            snapshot,
            returns_frame,
            fold_reports,
            seed=int(settings["seed"]),
        )

    passes = all(
        bool(regime_result["passes"])
        for market_result in market_results.values()
        for regime_result in market_result["regimes"].values()
    )
    verdict = "supported" if passes else "rejected"
    failure_reasons = [
        f"{market} {regime} lower confidence bound is not positive"
        for market, market_result in market_results.items()
        for regime, regime_result in market_result["regimes"].items()
        if not regime_result["passes"]
    ]
    return {
        "canonical_signature": SIGNATURE,
        "candidate_count": 1,
        "candidates": [
            {
                "name": "fixed_lagged_drawdown_state_regimes",
                "verdict": "pass" if passes else "reject",
                "failure_reasons": failure_reasons,
            }
        ],
        "verdict": verdict,
        "hypothesis": (
            "BTC-USDT and ETH-USDT net rolling OOS returns have positive annualized "
            "arithmetic means both at prior 60-session highs and while underwater."
        ),
        "method": {
            "drawdown_lookback": DRAWDOWN_LOOKBACK,
            "test_bars": TEST_BARS,
            "regime_threshold": 0.0,
            "annualization": ANNUALIZATION,
            "block_length": BLOCK_LENGTH,
            "resamples": RESAMPLES,
            "confidence": CONFIDENCE,
            "acceptance_rule": "all four lower confidence bounds must be strictly positive",
        },
        "markets": market_results,
        "source": {
            "provider": "OKX",
            "market_type": "spot",
            "timeframe": "1Dutc",
            "workflow_run_id": SOURCE_WORKFLOW_RUN_ID,
            "artifact_id": SOURCE_ARTIFACT_ID,
            "artifact_name": SOURCE_ARTIFACT_NAME,
            "artifact_sha256": SOURCE_ARTIFACT_SHA256,
            "source_code_commit": SOURCE_CODE_COMMIT,
            "observations_per_market": EXPECTED_OBSERVATIONS,
            "oos_start": "2020-01-11T00:00:00+00:00",
            "oos_end": "2026-06-07T00:00:00+00:00",
            "development_markets": True,
            "file_sha256": {
                market: {
                    "snapshot": settings["snapshot_sha256"],
                    "returns": settings["returns_sha256"],
                    "report": settings["report_sha256"],
                }
                for market, settings in MARKETS.items()
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run_analysis(args.artifact_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"verdict={result['verdict']}")
    print(f"candidate_count={result['candidate_count']}")
    print(f"output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
