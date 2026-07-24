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
    _ROOT / "reports" / "research" / "information-ratio-vs-volatility-benchmark" / "analysis.py"
)
_RESULT_PATH = (
    _ROOT / "reports" / "research" / "information-ratio-vs-volatility-benchmark" / "result.json"
)
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_RETURNS_FIXTURE = _FIXTURE_DIR / "okx_btc_usdt_oos_returns_20200111_20200219.csv"
_METADATA_FIXTURE = _FIXTURE_DIR / "okx_btc_usdt_oos_returns_20200111_20200219.metadata.json"

_SPEC = importlib.util.spec_from_file_location("information_ratio_analysis", _ANALYSIS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_ANALYSIS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ANALYSIS)


def _real_returns_frame() -> pd.DataFrame:
    metadata = json.loads(_METADATA_FIXTURE.read_text(encoding="utf-8"))
    assert hashlib.sha256(_RETURNS_FIXTURE.read_bytes()).hexdigest() == metadata["fixture_sha256"]
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    return pd.read_csv(_RETURNS_FIXTURE)


def test_return_loader_rejects_timezone_naive_timestamps(tmp_path: Path) -> None:
    frame = _real_returns_frame().rename(
        columns={"benchmark_buy_and_hold_return": _ANALYSIS.BENCHMARK_RETURN_COLUMN}
    )
    frame["timestamp"] = frame["timestamp"].str.replace("+00:00", "", regex=False)
    path = tmp_path / "timezone-naive-return-copy.csv"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="explicit timezone offset"):
        _ANALYSIS.load_returns(path)


def test_information_ratio_matches_independent_real_okx_calculation() -> None:
    frame = _real_returns_frame()
    strategy = frame["strategy_return"].to_numpy(dtype=float)
    benchmark = frame["benchmark_buy_and_hold_return"].to_numpy(dtype=float)
    active = strategy - benchmark
    expected = float(np.sqrt(365) * np.mean(active) / np.std(active, ddof=1))

    assert _ANALYSIS.information_ratio(strategy, benchmark) == pytest.approx(expected)


def test_paired_bootstrap_is_deterministic_and_preserves_contiguous_rows() -> None:
    frame = _real_returns_frame()
    strategy = frame["strategy_return"].to_numpy(dtype=float)
    benchmark = frame["benchmark_buy_and_hold_return"].to_numpy(dtype=float)
    kwargs = {
        "block_length": 10,
        "resamples": 200,
        "confidence": 0.95,
        "seed": 20260723,
    }

    first = _ANALYSIS.bootstrap_information_ratio(strategy, benchmark, **kwargs)
    second = _ANALYSIS.bootstrap_information_ratio(strategy, benchmark, **kwargs)

    assert first == second
    assert first["information_ratio"] == pytest.approx(
        _ANALYSIS.information_ratio(strategy, benchmark)
    )
    indices = _ANALYSIS.moving_block_indices(40, 10, np.random.default_rng(11))
    assert indices.shape == (40,)
    assert np.all(np.diff(indices.reshape(4, 10), axis=1) == 1)


def test_committed_report_records_one_rejected_candidate_with_provenance() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == _ANALYSIS.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["provenance"]["provider"] == "OKX"
    assert result["provenance"]["source_artifact_sha256"] == (
        "a4177288bba8a1599576688d8481546149512e96ad149c7b91f2e6f00d71fd31"
    )
    assert result["markets"]["BTC-USDT"]["return_file_sha256"] == (
        "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73"
    )
    assert result["markets"]["ETH-USDT"]["return_file_sha256"] == (
        "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6"
    )
    assert result["markets"]["BTC-USDT"]["ci_lower"] <= 0.0
    assert result["markets"]["ETH-USDT"]["ci_lower"] <= 0.0
