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
    / "expected-shortfall-vs-volatility-benchmark"
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
FIXTURE_SHA256 = "20a7125cafcf4c4b88275193b6afcce9d7ea570ba7d60402b3cab301bebb6503"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("expected_shortfall_vol_analysis", ANALYSIS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_returns() -> tuple[np.ndarray, np.ndarray]:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["instrument"] == "BTC-USDT"
    assert metadata["timeframe"] == "1Dutc"
    assert metadata["fixture_sha256"] == FIXTURE_SHA256
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == FIXTURE_SHA256
    frame = pd.read_csv(FIXTURE_PATH)
    return (
        frame["strategy_return"].to_numpy(dtype=float),
        frame["benchmark_volatility_targeted_long_return"].to_numpy(dtype=float),
    )


def _expected_shortfall(values: np.ndarray, tail_fraction: float) -> float:
    tail_count = math.ceil(len(values) * tail_fraction)
    return float(np.mean(np.sort(values)[:tail_count]))


def test_expected_shortfall_delta_uses_real_okx_paired_returns() -> None:
    analysis = _load_analysis()
    strategy, benchmark = _fixture_returns()

    result = analysis.expected_shortfall_delta(
        strategy,
        benchmark,
        tail_fraction=0.05,
    )

    expected_strategy_es = _expected_shortfall(strategy, 0.05)
    expected_benchmark_es = _expected_shortfall(benchmark, 0.05)
    assert result["strategy_expected_shortfall"] == pytest.approx(expected_strategy_es)
    assert result["benchmark_expected_shortfall"] == pytest.approx(expected_benchmark_es)
    assert result["observed_delta"] == pytest.approx(expected_strategy_es - expected_benchmark_es)


def test_bootstrap_resamples_strategy_and_benchmark_rows_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    strategy, benchmark = _fixture_returns()
    sample_indices = (
        np.concatenate((np.arange(0, 20), np.arange(10, 30))),
        np.concatenate((np.arange(20, 40), np.arange(5, 25))),
    )
    samples = iter(sample_indices)
    monkeypatch.setattr(
        analysis,
        "moving_block_indices",
        lambda observation_count, block_length, rng: next(samples),
    )

    result = analysis.bootstrap_expected_shortfall_delta(
        strategy,
        benchmark,
        tail_fraction=0.05,
        block_length=20,
        resamples=2,
        confidence=0.95,
        seed=17,
    )

    expected_deltas = [
        _expected_shortfall(strategy[indices], 0.05) - _expected_shortfall(benchmark[indices], 0.05)
        for indices in sample_indices
    ]
    assert result["ci_lower"] == pytest.approx(np.quantile(expected_deltas, 0.025))
    assert result["ci_upper"] == pytest.approx(np.quantile(expected_deltas, 0.975))
    assert result["probability_delta_positive"] == pytest.approx(
        np.mean(np.asarray(expected_deltas) > 0.0)
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


def test_result_records_single_supported_candidate_and_bound_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 1,
        "rejected": 0,
    }
    assert result["verdict"] == "supported"
    assert result["rejection_reason"] is None
    assert result["settings"]["benchmark"] == "volatility-targeted long"
    assert result["provenance"]["source_artifact_id"] == 8552001681
    assert result["provenance"]["source_artifact_sha256"] == (
        "e875970e048fdb6eb1a946330a8229ac445378a165c196de5e88abdde4b14576"
    )
    assert result["markets"]["BTC-USDT"]["observations"] == 2385
    assert result["markets"]["ETH-USDT"]["observations"] == 2385
    assert result["markets"]["BTC-USDT"]["observed_delta"] == pytest.approx(0.03019532258994361)
    assert result["markets"]["ETH-USDT"]["observed_delta"] == pytest.approx(0.028569380467662116)
    assert result["markets"]["BTC-USDT"]["ci_lower"] > 0.0
    assert result["markets"]["ETH-USDT"]["ci_lower"] > 0.0


def test_digest_mismatch_is_rejected_before_return_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    market_dir = tmp_path / "BTC-USDT"
    market_dir.mkdir()
    copied = market_dir / "walk_forward_returns.csv"
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
        lambda path: pytest.fail("return input must not be parsed after digest mismatch"),
    )

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        analysis.analyze_market(tmp_path, "BTC-USDT")
