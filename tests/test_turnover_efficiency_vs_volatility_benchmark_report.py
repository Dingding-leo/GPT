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
    _ROOT / "reports" / "research" / "turnover-efficiency-vs-volatility-benchmark" / "analysis.py"
)
_RESULT_PATH = (
    _ROOT / "reports" / "research" / "turnover-efficiency-vs-volatility-benchmark" / "result.json"
)
_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_TURNOVER_FIXTURE = _FIXTURE_DIR / "okx_btc_usdt_oos_turnover_20200111_20200219.csv"
_METADATA_FIXTURE = _FIXTURE_DIR / "okx_btc_usdt_oos_turnover_20200111_20200219.metadata.json"

_SPEC = importlib.util.spec_from_file_location("turnover_efficiency_analysis", _ANALYSIS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_ANALYSIS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ANALYSIS)


def _real_turnover_frame() -> pd.DataFrame:
    metadata = json.loads(_METADATA_FIXTURE.read_text(encoding="utf-8"))
    assert hashlib.sha256(_TURNOVER_FIXTURE.read_bytes()).hexdigest() == metadata["fixture_sha256"]
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    frame = pd.read_csv(_TURNOVER_FIXTURE)
    assert len(frame) == metadata["rows"]
    assert frame["timestamp"].iloc[0] == metadata["start"]
    assert frame["timestamp"].iloc[-1] == metadata["end"]
    return frame


def test_return_per_turnover_matches_independent_real_okx_calculation() -> None:
    frame = _real_turnover_frame()
    strategy_returns = frame["strategy_return"].to_numpy(dtype=float)
    strategy_turnover = frame["strategy_turnover"].to_numpy(dtype=float)
    benchmark_returns = frame["benchmark_volatility_targeted_long_return"].to_numpy(dtype=float)
    benchmark_turnover = frame["benchmark_volatility_targeted_long_turnover"].to_numpy(dtype=float)

    expected_strategy = float(strategy_returns.sum() / strategy_turnover.sum())
    expected_benchmark = float(benchmark_returns.sum() / benchmark_turnover.sum())

    assert _ANALYSIS.return_per_turnover(strategy_returns, strategy_turnover) == pytest.approx(
        expected_strategy
    )
    assert _ANALYSIS.return_per_turnover(benchmark_returns, benchmark_turnover) == pytest.approx(
        expected_benchmark
    )


def test_paired_efficiency_bootstrap_is_deterministic_and_preserves_blocks() -> None:
    frame = _real_turnover_frame()
    kwargs = {
        "block_length": 10,
        "resamples": 200,
        "confidence": 0.95,
        "seed": 20260723,
    }
    inputs = (
        frame["strategy_return"].to_numpy(dtype=float),
        frame["strategy_turnover"].to_numpy(dtype=float),
        frame["benchmark_volatility_targeted_long_return"].to_numpy(dtype=float),
        frame["benchmark_volatility_targeted_long_turnover"].to_numpy(dtype=float),
    )

    first = _ANALYSIS.bootstrap_efficiency_delta(*inputs, **kwargs)
    second = _ANALYSIS.bootstrap_efficiency_delta(*inputs, **kwargs)

    assert first == second
    assert first["observed_delta"] == pytest.approx(
        _ANALYSIS.return_per_turnover(inputs[0], inputs[1])
        - _ANALYSIS.return_per_turnover(inputs[2], inputs[3])
    )

    indices = _ANALYSIS.moving_block_indices(40, 10, np.random.default_rng(17))
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
        "88f5457a66e756384386a9f9712b029bcefbb2335f881f17a75200180b071414"
    )
    assert result["markets"]["BTC-USDT"]["return_file_sha256"] == (
        "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73"
    )
    assert result["markets"]["ETH-USDT"]["return_file_sha256"] == (
        "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6"
    )
    for market in _ANALYSIS.MARKETS:
        market_result = result["markets"][market]
        assert market_result["observed_delta"] < 0.0
        assert market_result["ci_lower"] <= 0.0
        assert market_result["benchmark_return_maximum_reconstruction_error"] <= (
            _ANALYSIS.BENCHMARK_MATCH_TOLERANCE
        )
