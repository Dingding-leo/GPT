from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).parents[1]
_ANALYSIS_PATH = _ROOT / "reports" / "research" / "sortino-vs-volatility-benchmark" / "analysis.py"
_RESULT_PATH = _ROOT / "reports" / "research" / "sortino-vs-volatility-benchmark" / "result.json"
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_RETURNS_FIXTURE = _FIXTURE_DIR / "okx_btc_usdt_oos_returns_20200111_20200219.csv"
_METADATA_FIXTURE = _FIXTURE_DIR / "okx_btc_usdt_oos_returns_20200111_20200219.metadata.json"

_SPEC = importlib.util.spec_from_file_location("sortino_benchmark_analysis", _ANALYSIS_PATH)
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


def test_sortino_matches_independent_real_okx_calculation() -> None:
    values = _real_returns_frame()["benchmark_buy_and_hold_return"].to_numpy(dtype=float)
    downside_deviation = math.sqrt(float(np.mean(np.square(np.minimum(values, 0.0)))))
    expected = float(np.mean(values)) * math.sqrt(365) / downside_deviation

    assert _ANALYSIS.annualized_sortino(values) == pytest.approx(expected)


def test_paired_sortino_bootstrap_is_deterministic_and_preserves_rows() -> None:
    frame = _real_returns_frame()
    strategy = frame["strategy_return"].to_numpy(dtype=float)
    benchmark = frame["benchmark_buy_and_hold_return"].to_numpy(dtype=float)
    kwargs = {
        "block_length": 10,
        "resamples": 200,
        "confidence": 0.95,
        "seed": 20260723,
    }

    first = _ANALYSIS.bootstrap_sortino_delta(strategy, benchmark, **kwargs)
    second = _ANALYSIS.bootstrap_sortino_delta(strategy, benchmark, **kwargs)

    assert first == second
    assert first["observed_delta"] == pytest.approx(
        _ANALYSIS.annualized_sortino(strategy) - _ANALYSIS.annualized_sortino(benchmark)
    )

    indices = _ANALYSIS.moving_block_indices(40, 10, np.random.default_rng(11))
    assert indices.shape == (40,)
    assert np.all(np.diff(indices.reshape(4, 10), axis=1) == 1)


def test_committed_report_records_one_rejected_candidate_with_provenance() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == _ANALYSIS.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "rejected"
    assert result["provenance"]["provider"] == "OKX"
    assert result["provenance"]["source_artifact_sha256"] == (
        "30523ece44c47c7c3317f7a5f5e6273eb5886cccb213dae2cc177b86dce007df"
    )
    assert result["markets"]["BTC-USDT"]["return_file_sha256"] == (
        "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73"
    )
    assert result["markets"]["ETH-USDT"]["return_file_sha256"] == (
        "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6"
    )
    assert result["markets"]["BTC-USDT"]["ci_lower"] <= 0.0
    assert result["markets"]["ETH-USDT"]["ci_lower"] <= 0.0
