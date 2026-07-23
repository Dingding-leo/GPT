from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).parents[1]
_ANALYSIS_PATH = (
    _ROOT / "reports/research/return-skewness-vs-volatility-benchmark/analysis.py"
)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")
_FIXTURE_PATH = (
    _ROOT
    / "tests/fixtures/okx_btc_usdt_oos_strategy_volatility_benchmark_20200111_20200219.csv"
)
_METADATA_PATH = _FIXTURE_PATH.with_suffix(".metadata.json")

_SPEC = importlib.util.spec_from_file_location("return_skewness_analysis", _ANALYSIS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_ANALYSIS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ANALYSIS)


def _fixture() -> pd.DataFrame:
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(_FIXTURE_PATH.read_bytes()).hexdigest() == metadata["fixture_sha256"]
    frame = pd.read_csv(_FIXTURE_PATH)
    assert len(frame) == metadata["rows"]
    assert frame["timestamp"].iloc[0] == metadata["start"]
    assert frame["timestamp"].iloc[-1] == metadata["end"]
    return frame


def _independent_adjusted_skewness(values: np.ndarray) -> float:
    observed = np.asarray(values, dtype=float)
    count = observed.size
    centered = observed - observed.mean()
    second = np.mean(centered**2)
    third = np.mean(centered**3)
    return float(np.sqrt(count * (count - 1)) / (count - 2) * third / second**1.5)


def test_real_okx_fixture_and_adjusted_skewness_formula() -> None:
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    frame = _fixture()

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["source_artifact_id"] == 8550139614
    for column in (
        "strategy_return",
        "benchmark_volatility_targeted_long_return",
    ):
        values = frame[column].to_numpy(dtype=float)
        assert _ANALYSIS.adjusted_sample_skewness(values) == pytest.approx(
            _independent_adjusted_skewness(values)
        )


def test_paired_block_bootstrap_is_deterministic_and_contiguous() -> None:
    frame = _fixture()
    strategy = frame["strategy_return"].to_numpy(dtype=float)
    benchmark = frame["benchmark_volatility_targeted_long_return"].to_numpy(dtype=float)
    kwargs = {
        "block_length": 10,
        "resamples": 200,
        "confidence": 0.95,
        "seed": 2026072311,
    }

    first = _ANALYSIS.bootstrap_skewness_delta(strategy, benchmark, **kwargs)
    second = _ANALYSIS.bootstrap_skewness_delta(strategy, benchmark, **kwargs)
    assert first == second
    assert first["observed_delta"] == pytest.approx(
        _independent_adjusted_skewness(strategy)
        - _independent_adjusted_skewness(benchmark)
    )

    indices = _ANALYSIS.moving_block_indices(40, 10, np.random.default_rng(17))
    assert np.all(np.diff(indices.reshape(4, 10), axis=1) == 1)
    assert indices.min() >= 0
    assert indices.max() < 40


def test_timestamp_validation_rejects_timezone_naive_copy(tmp_path: Path) -> None:
    frame = _fixture().copy()
    frame["timestamp"] = frame["timestamp"].str.replace("+00:00", "", regex=False)
    malformed = tmp_path / "timezone-naive.csv"
    frame.to_csv(malformed, index=False)

    with pytest.raises(ValueError, match="explicit timezone offset"):
        _ANALYSIS.load_returns(malformed)


def test_committed_result_records_complete_rejected_candidate() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == _ANALYSIS.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "rejected"
    assert result["markets"]["BTC-USDT"]["passed"] is True
    assert result["markets"]["ETH-USDT"]["passed"] is False
    assert result["provenance"]["source_artifact_sha256"] == (
        "e528db2a672d5880a9374c371df2250f51c89a4951b55fe3f2edde34a8db8662"
    )
    assert result["markets"]["BTC-USDT"]["return_file_sha256"] == (
        "ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce"
    )
    assert result["markets"]["ETH-USDT"]["return_file_sha256"] == (
        "bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047"
    )
