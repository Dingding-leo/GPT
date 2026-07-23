from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ANALYSIS_PATH = (
    _ROOT
    / "reports"
    / "research"
    / "exposure-efficiency-vs-volatility-benchmark"
    / "analysis.py"
)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")
_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "okx_btc_usdt_oos_exposure_20200111_20200219"
)


def _load_analysis():
    spec = importlib.util.spec_from_file_location("exposure_efficiency_analysis", _ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load exposure-efficiency analysis")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_fixture_metric_and_provenance() -> None:
    module = _load_analysis()
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    fixture_path = _FIXTURE_DIR / "returns.csv"
    observed_sha256 = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    assert observed_sha256 == metadata["fixture_sha256"]
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["timeframe"] == "1Dutc"
    assert metadata["observations"] == 40

    frame = pd.read_csv(fixture_path)
    strategy = module.annualized_return_per_exposure_day(
        frame["strategy_return"].to_numpy(dtype=float),
        frame["strategy_position"].to_numpy(dtype=float),
    )
    benchmark = module.annualized_return_per_exposure_day(
        frame["benchmark_return"].to_numpy(dtype=float),
        frame["benchmark_position"].to_numpy(dtype=float),
    )
    expected_strategy = (
        module.ANNUALIZATION
        * frame["strategy_return"].sum()
        / frame["strategy_position"].sum()
    )
    expected_benchmark = (
        module.ANNUALIZATION
        * frame["benchmark_return"].sum()
        / frame["benchmark_position"].sum()
    )
    assert strategy == pytest.approx(expected_strategy, abs=1e-15)
    assert benchmark == pytest.approx(expected_benchmark, abs=1e-15)


def test_paired_moving_blocks_are_deterministic_and_contiguous() -> None:
    module = _load_analysis()
    first = module.moving_block_indices(40, 8, np.random.default_rng(2026072321))
    second = module.moving_block_indices(40, 8, np.random.default_rng(2026072321))
    assert np.array_equal(first, second)
    assert len(first) == 40
    for start in range(0, 40, 8):
        block = first[start : start + 8]
        assert np.array_equal(np.diff(block), np.ones(7, dtype=int))


def test_result_records_single_rejected_candidate() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
    assert result["candidate_accounting"] == {"passed": 0, "rejected": 1, "searched": 1}
    assert result["verdict"] == "rejected"
    assert result["canonical_signature"].endswith("candidate_count=1")
    assert result["source"]["provider"] == "OKX"
    assert result["source"]["artifact_id"] == 8563252094
    assert result["markets"]["BTC-USDT"]["passed"] is False
    assert result["markets"]["ETH-USDT"]["passed"] is False
    assert result["markets"]["BTC-USDT"]["ci_lower"] <= 0.0
    assert result["markets"]["ETH-USDT"]["ci_lower"] <= 0.0


def test_metric_rejects_zero_exposure() -> None:
    module = _load_analysis()
    with pytest.raises(ValueError, match="total exposure-days must be positive"):
        module.annualized_return_per_exposure_day(np.array([0.0, 0.01]), np.zeros(2))
