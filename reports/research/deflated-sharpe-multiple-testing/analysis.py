from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

ANNUALIZATION = 365
EFFECTIVE_TRIALS = 27
PASS_PROBABILITY = 0.95
EXPECTED_OBSERVATIONS = 2340
SELECTION_BARS = 730
TEST_BARS = 90
EULER_MASCHERONI = 0.5772156649015329
SOURCE_WORKFLOW_RUN_ID = 29912901356
SOURCE_ARTIFACT_ID = 8526644006
SOURCE_ARTIFACT_NAME = "quant-research-source-904-attempt-1"
SOURCE_ARTIFACT_SHA256 = "e547d220d6f1f1649038387471c3cf9fef6da6d9f71d793f80ee2b0d114bcca4"
SOURCE_TESTED_COMMIT = "5528e1677fab9dd6e8b1b60ae00f2205f4116ead"
SOURCE_HEAD_COMMIT = "205864d115a9043cb15a6215f8e3d058edb4dd69"
SOURCE_BASE_COMMIT = "4f745926277fbf64ce06294e8c43322a1f9800e6"
MARKETS = {
    "BTC-USDT": {
        "returns_sha256": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "report_sha256": "663ec9d7aa70b5e41cffc9f3b68f049d255e4a65a236019d85d33ae9381b13df",
    },
    "ETH-USDT": {
        "returns_sha256": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        "report_sha256": "f536fa4d9d01d8ffca83b5eff90da76662c5031424f0dadee501b4bb2d7e3fc7",
    },
}
SIGNATURE = (
    "deflated-sharpe-independent-null-v1|markets=BTC-USDT,ETH-USDT|"
    "source=persisted-net-rolling-oos-returns|"
    "observed-sharpe=mean/std-ddof0|annualization=365|"
    "selection-adjustment=expected-maximum-of-independent-zero-skill-normal-trials|"
    "effective-trials=27|trial-standard-error=1/sqrt(n-1)|"
    "non-normality=fisher-pearson-skew-and-raw-kurtosis|"
    "pass=dsr-probability-at-least-0.95-for-both-markets|candidate_count=1"
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


def expected_maximum_null_z(effective_trials: int) -> float:
    if (
        isinstance(effective_trials, bool)
        or not isinstance(effective_trials, int)
        or effective_trials < 2
    ):
        raise ValueError("effective trial count must be an integer of at least two")
    normal = NormalDist()
    first = normal.inv_cdf(1.0 - 1.0 / effective_trials)
    second = normal.inv_cdf(1.0 - 1.0 / (effective_trials * math.e))
    return (1.0 - EULER_MASCHERONI) * first + EULER_MASCHERONI * second


def deflated_sharpe_statistics(
    returns: pd.Series | np.ndarray,
    *,
    effective_trials: int = EFFECTIVE_TRIALS,
    annualization: int = ANNUALIZATION,
) -> dict[str, float | int | bool]:
    if isinstance(annualization, bool) or not isinstance(annualization, int) or annualization < 2:
        raise ValueError("annualization must be an integer of at least two")
    values = pd.to_numeric(pd.Series(returns), errors="raise").to_numpy(dtype=float)
    if len(values) < 3:
        raise ValueError("deflated Sharpe requires at least three observations")
    if not np.isfinite(values).all() or (values <= -1.0).any():
        raise ValueError("returns must be finite and greater than -100%")

    standard_deviation = float(values.std(ddof=0))
    if not standard_deviation > 0.0:
        raise ValueError("deflated Sharpe requires non-zero return volatility")

    observed_daily_sharpe = float(values.mean() / standard_deviation)
    return_series = pd.Series(values)
    sample_skewness = float(return_series.skew())
    sample_raw_kurtosis = float(return_series.kurt() + 3.0)
    if not math.isfinite(sample_skewness) or not math.isfinite(sample_raw_kurtosis):
        raise ValueError("return skewness and kurtosis must be finite")

    sample_size = len(values)
    expected_null_z = expected_maximum_null_z(effective_trials)
    benchmark_daily_sharpe = expected_null_z / math.sqrt(sample_size - 1)
    denominator_squared = (
        1.0
        - sample_skewness * observed_daily_sharpe
        + ((sample_raw_kurtosis - 1.0) / 4.0) * observed_daily_sharpe**2
    )
    if not math.isfinite(denominator_squared) or denominator_squared <= 0.0:
        raise ValueError("deflated Sharpe non-normality denominator must be positive")

    denominator = math.sqrt(denominator_squared)
    sample_scale = math.sqrt(sample_size - 1)
    deflated_z = (
        (observed_daily_sharpe - benchmark_daily_sharpe) * sample_scale / denominator
    )
    probabilistic_z = observed_daily_sharpe * sample_scale / denominator
    normal = NormalDist()
    deflated_probability = normal.cdf(deflated_z)
    probabilistic_probability = normal.cdf(probabilistic_z)
    annualization_scale = math.sqrt(annualization)

    return {
        "observations": sample_size,
        "effective_trials": effective_trials,
        "observed_daily_sharpe": observed_daily_sharpe,
        "observed_annualized_sharpe": observed_daily_sharpe * annualization_scale,
        "sample_skewness": sample_skewness,
        "sample_raw_kurtosis": sample_raw_kurtosis,
        "expected_maximum_null_z": expected_null_z,
        "deflated_benchmark_daily_sharpe": benchmark_daily_sharpe,
        "deflated_benchmark_annualized_sharpe": benchmark_daily_sharpe
        * annualization_scale,
        "probabilistic_sharpe_probability_vs_zero": probabilistic_probability,
        "deflated_sharpe_z": deflated_z,
        "deflated_sharpe_probability": deflated_probability,
        "passes": bool(deflated_probability >= PASS_PROBABILITY),
    }


def _validate_report(report: dict[str, object]) -> None:
    settings = report.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("walk-forward report settings must be a mapping")
    if settings.get("candidate_count") != EFFECTIVE_TRIALS:
        raise ValueError("walk-forward report candidate count changed")
    if settings.get("selection_bars") != SELECTION_BARS:
        raise ValueError("walk-forward report selection length changed")
    if settings.get("test_bars") != TEST_BARS:
        raise ValueError("walk-forward report test length changed")
    if settings.get("non_overlapping_test_folds") is not True:
        raise ValueError("walk-forward report must declare non-overlapping test folds")
    base_config = settings.get("base_config")
    if not isinstance(base_config, dict):
        raise ValueError("walk-forward report base configuration must be a mapping")
    if base_config.get("annualization") != ANNUALIZATION:
        raise ValueError("walk-forward report annualization changed")
    if base_config.get("transaction_cost_bps") != 10.0:
        raise ValueError("walk-forward report transaction cost changed")


def load_market_returns(
    artifact_dir: Path,
    *,
    market: str,
    expected_returns_sha256: str,
    expected_report_sha256: str,
) -> pd.Series:
    market_dir = artifact_dir / market
    returns_path = market_dir / "walk_forward_returns.csv"
    report_path = market_dir / "walk_forward.json"
    for path, expected in {
        returns_path: expected_returns_sha256,
        report_path: expected_report_sha256,
    }.items():
        actual = file_sha256(path)
        if actual != expected:
            raise ValueError(f"{path.name} hash mismatch: expected {expected}, actual {actual}")

    frame = pd.read_csv(returns_path)
    missing = {"timestamp", "strategy_return", "fold"} - set(frame)
    if missing:
        raise ValueError(f"return file is missing required columns: {sorted(missing)}")
    if len(frame) != EXPECTED_OBSERVATIONS:
        raise ValueError(f"return file must contain exactly {EXPECTED_OBSERVATIONS} observations")
    index = explicit_daily_utc_index(frame["timestamp"], label="return")
    strategy_returns = pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(
        dtype=float
    )
    folds = pd.to_numeric(frame["fold"], errors="raise").to_numpy(dtype=float)
    if not np.isfinite(strategy_returns).all() or (strategy_returns <= -1.0).any():
        raise ValueError("strategy returns must be finite and greater than -100%")
    if not np.isfinite(folds).all() or not np.equal(folds, np.floor(folds)).all():
        raise ValueError("fold identifiers must be finite integers")

    report = json.loads(report_path.read_text(encoding="utf-8"))
    _validate_report(report)
    fold_reports = report.get("folds")
    if not isinstance(fold_reports, list):
        raise ValueError("walk-forward report folds must be a list")
    fold_ids = [int(fold["fold"]) for fold in fold_reports]
    observed_fold_ids = sorted(set(folds.astype(int).tolist()))
    if fold_ids != list(range(1, len(fold_ids) + 1)) or observed_fold_ids != fold_ids:
        raise ValueError("return-file fold identifiers must match consecutive report folds")
    if any(int((folds == fold_id).sum()) != TEST_BARS for fold_id in fold_ids):
        raise ValueError("every OOS fold must contain the declared test-bar count")

    return pd.Series(strategy_returns, index=index, name="strategy_return")


def build_result(artifact_dir: Path) -> dict[str, object]:
    market_results: dict[str, object] = {}
    for market, evidence in MARKETS.items():
        returns = load_market_returns(
            artifact_dir,
            market=market,
            expected_returns_sha256=str(evidence["returns_sha256"]),
            expected_report_sha256=str(evidence["report_sha256"]),
        )
        market_results[market] = deflated_sharpe_statistics(returns)

    passes = all(bool(result["passes"]) for result in market_results.values())
    failure_reason = (
        None
        if passes
        else "At least one market has a deflated Sharpe probability below 95%."
    )
    return {
        "hypothesis": (
            "BTC-USDT and ETH-USDT aggregate net rolling OOS Sharpe ratios exceed the "
            "expected maximum under 27 independent zero-skill trials with at least 95% "
            "probability after sample skewness and kurtosis are included."
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
            "effective_trials": EFFECTIVE_TRIALS,
            "pass_probability": PASS_PROBABILITY,
            "observed_sharpe_standard_deviation_ddof": 0,
            "sample_skewness": "Fisher-Pearson adjusted sample skewness",
            "sample_kurtosis": "unbiased Fisher excess kurtosis plus three",
            "selection_benchmark": (
                "Bailey-Lopez de Prado expected maximum under independent zero-skill "
                "normal trials, scaled by 1/sqrt(n-1)"
            ),
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
            "source_tested_commit": SOURCE_TESTED_COMMIT,
            "source_persistent_head": SOURCE_HEAD_COMMIT,
            "source_tested_base": SOURCE_BASE_COMMIT,
            "oos_observations_per_market": EXPECTED_OBSERVATIONS,
            "oos_start": "2020-01-11T00:00:00+00:00",
            "oos_end": "2026-06-07T00:00:00+00:00",
            "markets": MARKETS,
        },
        "markets": market_results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Test multiple-testing-adjusted OOS Sharpe evidence with DSR."
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
