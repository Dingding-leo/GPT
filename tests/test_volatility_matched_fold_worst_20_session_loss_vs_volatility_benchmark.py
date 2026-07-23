from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT
    / "reports"
    / "research"
    / "volatility-matched-fold-worst-20-session-loss-vs-volatility-benchmark"
    / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "okx_btc_usdt_oos_volatility_benchmark_20200111_20200219"
)
FIXTURE_PATH = FIXTURE_DIR / "returns.csv"
METADATA_PATH = FIXTURE_DIR / "metadata.json"


def _load_analysis():
    spec = importlib.util.spec_from_file_location(
        "volatility_matched_acute_loss",
        ANALYSIS_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_fixture() -> pd.DataFrame:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["instrument"] == "BTC-USDT"
    assert metadata["timeframe"] == "1Dutc"
    assert metadata["source_artifact_id"] == 8553558024
    fixture_hash = hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest()
    assert fixture_hash == metadata["fixture_sha256"]
    return pd.read_csv(FIXTURE_PATH)


def test_volatility_matching_and_worst_window_use_aligned_real_returns() -> None:
    analysis = _load_analysis()
    frame = _real_fixture()
    strategy = frame[analysis.STRATEGY_RETURN_COLUMN].to_numpy(dtype=float)
    benchmark = frame[analysis.BENCHMARK_RETURN_COLUMN].to_numpy(dtype=float)

    expected_scale = float(np.std(strategy, ddof=1) / np.std(benchmark, ddof=1))
    observed_scale = analysis.sample_volatility_scale(strategy, benchmark)
    metrics = analysis.fold_worst_window_deltas(frame, fold_length=40, window=20)

    assert observed_scale == pytest.approx(expected_scale)
    assert metrics.loc[0, "benchmark_volatility_scale"] == pytest.approx(
        expected_scale
    )
    expected_strategy_worst = min(
        float(np.prod(1.0 + strategy[start : start + 20]) - 1.0)
        for start in range(21)
    )
    scaled_benchmark = benchmark * expected_scale
    expected_benchmark_worst = min(
        float(np.prod(1.0 + scaled_benchmark[start : start + 20]) - 1.0)
        for start in range(21)
    )
    assert metrics.loc[0, "strategy_worst_window_return"] == pytest.approx(
        expected_strategy_worst
    )
    assert metrics.loc[
        0, "volatility_matched_benchmark_worst_window_return"
    ] == pytest.approx(expected_benchmark_worst)


def test_fold_block_bootstrap_reuses_consecutive_observed_fold_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    frame = _real_fixture()
    strategy = frame[analysis.STRATEGY_RETURN_COLUMN].to_numpy(dtype=float)
    observed = np.asarray(
        [
            analysis.worst_compounded_window_return(
                strategy[start : start + 10],
                window=5,
            )
            for start in range(0, 40, 10)
        ]
    )
    sample_indices = (
        np.asarray([0, 1, 2, 0]),
        np.asarray([1, 2, 3, 1]),
    )
    samples = iter(sample_indices)
    monkeypatch.setattr(
        analysis,
        "moving_block_indices",
        lambda observation_count, block_length, rng: next(samples),
    )

    result = analysis.bootstrap_mean_delta(
        observed,
        block_length=3,
        resamples=2,
        confidence=0.95,
        seed=7,
    )

    expected_means = np.asarray(
        [float(np.mean(observed[indices])) for indices in sample_indices]
    )
    assert result["ci_lower"] == pytest.approx(np.quantile(expected_means, 0.025))
    assert result["ci_upper"] == pytest.approx(np.quantile(expected_means, 0.975))


def test_zero_benchmark_volatility_fails_before_metric_calculation() -> None:
    analysis = _load_analysis()
    frame = _real_fixture()
    strategy = frame[analysis.STRATEGY_RETURN_COLUMN].to_numpy(dtype=float)
    benchmark_first = frame[analysis.BENCHMARK_RETURN_COLUMN].iloc[0]
    corrupted_benchmark = np.full(len(frame), benchmark_first)

    with pytest.raises(ValueError, match="benchmark sample volatility"):
        analysis.sample_volatility_scale(strategy, corrupted_benchmark)


def test_timezone_naive_copy_fails_before_metric_calculation(tmp_path: Path) -> None:
    analysis = _load_analysis()
    frame = _real_fixture()
    frame["timestamp"] = frame["timestamp"].str.replace("+00:00", "", regex=False)
    path = tmp_path / "naive.csv"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="explicit timezone"):
        analysis.load_returns(path)


def test_result_records_one_rejected_candidate_and_bound_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["provenance"]["source_workflow_run_id"] == 29982033676
    assert result["provenance"]["source_artifact_id"] == 8553558024
    assert result["provenance"]["source_artifact_sha256"] == (
        "382f20d2350ebd5cb79aafdf3c901eda4ec0f1663c33d0bae9b70a920d3c82b7"
    )
    btc = result["markets"]["BTC-USDT"]
    eth = result["markets"]["ETH-USDT"]
    assert btc["complete_folds"] == eth["complete_folds"] == 26
    assert btc["excluded_trailing_rows"] == eth["excluded_trailing_rows"] == 45
    assert btc["observed_mean_delta"] == pytest.approx(-0.01064436588127051)
    assert eth["observed_mean_delta"] == pytest.approx(-0.016774498228293185)
    assert btc["ci_lower"] < 0.0
    assert eth["ci_upper"] < 0.0
