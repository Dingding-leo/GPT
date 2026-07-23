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
    / "fold-worst-20-session-loss-vs-volatility-benchmark"
    / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
METADATA_PATH = FIXTURE_DIR / "metadata.json"
BTC_FIXTURE_PATH = FIXTURE_DIR / "btc_usdt_returns.csv"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("fold_worst_window_loss_analysis", ANALYSIS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_btc_returns() -> np.ndarray:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["market_type"] == "spot"
    assert metadata["timeframe"] == "1Dutc"
    instrument = metadata["instruments"]["BTC-USDT"]
    assert hashlib.sha256(BTC_FIXTURE_PATH.read_bytes()).hexdigest() == instrument["fixture_sha256"]
    frame = pd.read_csv(BTC_FIXTURE_PATH)
    return frame["strategy_return"].to_numpy(dtype=float)


def test_worst_compounded_window_uses_observed_real_returns() -> None:
    analysis = _load_analysis()
    returns = _real_btc_returns()[:20]
    expected = min(
        float(np.prod(1.0 + returns[start : start + 10]) - 1.0)
        for start in range(11)
    )

    observed = analysis.worst_compounded_window_return(returns, window=10)

    assert observed == pytest.approx(expected)


def test_fold_metric_excludes_only_a_trailing_short_fold() -> None:
    analysis = _load_analysis()
    returns = _real_btc_returns()
    frame = pd.DataFrame(
        {
            "fold": np.repeat([1, 2], 20),
            analysis.STRATEGY_RETURN_COLUMN: returns,
            analysis.BENCHMARK_RETURN_COLUMN: returns,
        }
    )
    frame = pd.concat(
        [
            frame,
            pd.DataFrame(
                {
                    "fold": [3] * 5,
                    analysis.STRATEGY_RETURN_COLUMN: returns[:5],
                    analysis.BENCHMARK_RETURN_COLUMN: returns[:5],
                }
            ),
        ],
        ignore_index=True,
    )

    metrics = analysis.fold_worst_window_deltas(frame, fold_length=20, window=10)

    assert metrics["fold"].tolist() == [1, 2]
    np.testing.assert_allclose(metrics["delta"].to_numpy(dtype=float), np.zeros(2))


def test_fold_metric_rejects_oversized_trailing_fold_without_calculating_metrics() -> None:
    analysis = _load_analysis()
    returns = _real_btc_returns()
    frame = pd.DataFrame(
        {
            "fold": [1] * 19 + [2] * 21,
            analysis.STRATEGY_RETURN_COLUMN: returns,
            analysis.BENCHMARK_RETURN_COLUMN: returns,
        }
    )

    with pytest.raises(ValueError, match="exceed the declared complete length"):
        analysis.fold_worst_window_deltas(frame, fold_length=20, window=10)


def test_fold_block_bootstrap_reuses_consecutive_observed_fold_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    returns = _real_btc_returns()
    observed_fold_statistics = np.asarray(
        [
            analysis.worst_compounded_window_return(returns[start : start + 10], window=5)
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
        observed_fold_statistics,
        block_length=3,
        resamples=2,
        confidence=0.95,
        seed=7,
    )

    expected_means = np.asarray(
        [float(np.mean(observed_fold_statistics[indices])) for indices in sample_indices]
    )
    assert result["ci_lower"] == pytest.approx(np.quantile(expected_means, 0.025))
    assert result["ci_upper"] == pytest.approx(np.quantile(expected_means, 0.975))


def test_result_records_one_supported_candidate_and_bound_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 1,
        "rejected": 0,
    }
    assert result["verdict"] == "supported"
    assert result["provenance"]["source_workflow_run_id"] == 29982033676
    assert result["provenance"]["source_artifact_id"] == 8553558024
    assert result["provenance"]["source_artifact_sha256"] == (
        "382f20d2350ebd5cb79aafdf3c901eda4ec0f1663c33d0bae9b70a920d3c82b7"
    )
    assert result["markets"]["BTC-USDT"]["complete_folds"] == 26
    assert result["markets"]["ETH-USDT"]["complete_folds"] == 26
    assert result["markets"]["BTC-USDT"]["excluded_trailing_rows"] == 45
    assert result["markets"]["ETH-USDT"]["excluded_trailing_rows"] == 45
    assert result["markets"]["BTC-USDT"]["ci_lower"] > 0.0
    assert result["markets"]["ETH-USDT"]["ci_lower"] > 0.0
    assert result["markets"]["BTC-USDT"]["observed_mean_delta"] == pytest.approx(
        0.10058014337943202
    )
    assert result["markets"]["ETH-USDT"]["observed_mean_delta"] == pytest.approx(
        0.0880561681794593
    )
