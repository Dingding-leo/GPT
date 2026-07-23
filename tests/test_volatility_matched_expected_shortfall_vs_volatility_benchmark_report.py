from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT
    / "reports"
    / "research"
    / "volatility-matched-expected-shortfall-vs-volatility-benchmark"
    / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "okx_btc_usdt_oos_volatility_matched_es_20200111_20200219"
)
FIXTURE_PATH = FIXTURE_DIR / "returns.csv"
METADATA_PATH = FIXTURE_DIR / "metadata.json"
FIXTURE_SHA256 = "20a7125cafcf4c4b88275193b6afcce9d7ea570ba7d60402b3cab301bebb6503"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("volatility_matched_es_benchmark", ANALYSIS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_returns() -> tuple[np.ndarray, np.ndarray]:
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == FIXTURE_SHA256
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["fixture_sha256"] == FIXTURE_SHA256
    assert metadata["provider"] == "OKX"
    assert metadata["instrument"] == "BTC-USDT"
    assert metadata["timeframe"] == "1Dutc"
    assert metadata["rows"] == 40

    frame = pd.read_csv(FIXTURE_PATH)
    return (
        frame["strategy_return"].to_numpy(dtype=float),
        frame["benchmark_volatility_targeted_long_return"].to_numpy(dtype=float),
    )


def _expected_shortfall(values: np.ndarray, tail_fraction: float) -> float:
    tail_count = math.ceil(len(values) * tail_fraction)
    return float(np.mean(np.sort(values)[:tail_count]))


def test_volatility_matching_and_expected_shortfall_use_real_okx_returns() -> None:
    analysis = _load_analysis()
    strategy, benchmark = _fixture_returns()

    result = analysis.volatility_matched_expected_shortfall_delta(
        strategy,
        benchmark,
        tail_fraction=0.05,
    )

    expected_scale = float(np.std(strategy, ddof=1) / np.std(benchmark, ddof=1))
    matched_benchmark = benchmark * expected_scale
    expected_strategy_es = _expected_shortfall(strategy, 0.05)
    expected_benchmark_es = _expected_shortfall(matched_benchmark, 0.05)

    assert result["volatility_match_scale"] == pytest.approx(expected_scale)
    assert np.std(matched_benchmark, ddof=1) == pytest.approx(np.std(strategy, ddof=1))
    assert result["strategy_expected_shortfall"] == pytest.approx(expected_strategy_es)
    assert result["volatility_matched_benchmark_expected_shortfall"] == pytest.approx(
        expected_benchmark_es
    )
    assert result["observed_delta"] == pytest.approx(expected_strategy_es - expected_benchmark_es)


def test_bootstrap_recomputes_scale_for_each_paired_real_return_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    strategy, benchmark = _fixture_returns()
    sample_sets = (
        np.concatenate((np.arange(0, 20), np.arange(10, 30))),
        np.concatenate((np.arange(20, 40), np.arange(5, 25))),
    )
    samples = iter(sample_sets)
    monkeypatch.setattr(
        analysis,
        "moving_block_indices",
        lambda observation_count, block_length, rng: next(samples),
    )

    result = analysis.bootstrap_volatility_matched_expected_shortfall_delta(
        strategy,
        benchmark,
        tail_fraction=0.05,
        block_length=20,
        resamples=2,
        confidence=0.95,
        seed=17,
    )

    expected_deltas = []
    expected_scales = []
    for indices in sample_sets:
        sampled_strategy = strategy[indices]
        sampled_benchmark = benchmark[indices]
        scale = float(np.std(sampled_strategy, ddof=1) / np.std(sampled_benchmark, ddof=1))
        expected_scales.append(scale)
        expected_deltas.append(
            _expected_shortfall(sampled_strategy, 0.05)
            - _expected_shortfall(sampled_benchmark * scale, 0.05)
        )

    assert result["ci_lower"] == pytest.approx(np.quantile(expected_deltas, 0.025))
    assert result["ci_upper"] == pytest.approx(np.quantile(expected_deltas, 0.975))
    assert result["bootstrap_scale_ci_lower"] == pytest.approx(
        np.quantile(expected_scales, 0.025)
    )
    assert result["bootstrap_scale_ci_upper"] == pytest.approx(
        np.quantile(expected_scales, 0.975)
    )


def test_moving_blocks_are_deterministic_and_contiguous() -> None:
    analysis = _load_analysis()
    first = analysis.moving_block_indices(40, 10, np.random.default_rng(20260723))
    second = analysis.moving_block_indices(40, 10, np.random.default_rng(20260723))

    np.testing.assert_array_equal(first, second)
    assert len(first) == 40
    assert int(first.min()) >= 0
    assert int(first.max()) < 40
    for start in range(0, 40, 10):
        np.testing.assert_array_equal(np.diff(first[start : start + 10]), np.ones(9))


def test_result_records_single_rejected_candidate_and_bound_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["settings"]["volatility_scale_recomputed_per_resample"] is True
    assert result["provenance"]["source_artifact_id"] == 8559031387
    assert result["provenance"]["source_artifact_sha256"] == (
        "9d7f5c91ac46c8a3d5a3b0d34f569936bd70bc4197161ae5d977c2c6730e0c04"
    )
    assert result["markets"]["BTC-USDT"]["observations"] == 2385
    assert result["markets"]["ETH-USDT"]["observations"] == 2385
    assert result["markets"]["BTC-USDT"]["observed_delta"] == pytest.approx(
        -0.0009550359305191547
    )
    assert result["markets"]["ETH-USDT"]["observed_delta"] == pytest.approx(
        -0.004179768015039168
    )
    assert result["markets"]["ETH-USDT"]["ci_upper"] < 0.0


def test_digest_mismatch_is_rejected_before_metric_calculation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    copied = tmp_path / "returns.csv"
    copied.write_bytes(FIXTURE_PATH.read_bytes())
    monkeypatch.setitem(
        analysis.EXPECTED_RETURN_FILE_SHA256,
        "BTC-USDT",
        FIXTURE_SHA256,
    )
    assert analysis.verify_return_file_sha256(copied, "BTC-USDT") == FIXTURE_SHA256

    contents = copied.read_text(encoding="utf-8")
    copied.write_text(contents.replace("-0.0,", "-0.0001,", 1), encoding="utf-8")
    monkeypatch.setattr(
        analysis,
        "load_returns",
        lambda path: pytest.fail("metric input must not be parsed after digest mismatch"),
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        analysis.verify_return_file_sha256(copied, "BTC-USDT")
