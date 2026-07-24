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
    / "adaptive-selection-risk-vs-fixed-base"
    / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
SPEC = importlib.util.spec_from_file_location("adaptive_selection_risk_analysis", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _fixture_returns(market: str) -> np.ndarray:
    metadata = json.loads((FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    details = metadata["instruments"][market]
    path = REPOSITORY_ROOT / details["fixture_path"]
    assert metadata["provider"] == "OKX"
    assert metadata["timeframe"] == "1Dutc"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == details["fixture_sha256"]
    frame = pd.read_csv(path)
    assert len(frame) == details["observations"] == 40
    return pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(dtype=float)


def test_drawdown_and_calmar_match_independent_real_return_calculation() -> None:
    returns = _fixture_returns("BTC-USDT")
    nav = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    expected_drawdown = float(np.min(nav / np.maximum.accumulate(nav) - 1.0))
    growth = float(np.prod(1.0 + returns))
    expected_cagr = growth ** (analysis.ANNUALIZATION / len(returns)) - 1.0
    expected_calmar = expected_cagr / abs(expected_drawdown)

    assert analysis.max_drawdown(returns) == pytest.approx(expected_drawdown, abs=1e-15)
    assert analysis.cagr(returns) == pytest.approx(expected_cagr, abs=1e-15)
    assert analysis.calmar(returns) == pytest.approx(expected_calmar, abs=1e-15)


def test_paired_bootstrap_is_deterministic_on_real_return_extracts() -> None:
    btc = _fixture_returns("BTC-USDT")
    eth = _fixture_returns("ETH-USDT")
    first = analysis.paired_bootstrap_comparison(
        btc,
        eth,
        block_length=5,
        resamples=200,
        confidence=0.95,
        seed=20260722,
    )
    second = analysis.paired_bootstrap_comparison(
        btc,
        eth,
        block_length=5,
        resamples=200,
        confidence=0.95,
        seed=20260722,
    )

    assert first == second
    assert first["observations"] == 40
    assert len(first["max_drawdown_delta_interval"]) == 2
    assert len(first["calmar_delta_interval"]) == 2


def test_committed_result_records_single_rejected_hypothesis() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.SIGNATURE
    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["provenance"]["source_artifact_sha256"] == analysis.SOURCE_ARTIFACT_SHA256
    assert set(result["markets"]) == set(analysis.MARKETS)
    assert all(market["observations"] == 2340 for market in result["markets"].values())
    assert all(not market["passes"] for market in result["markets"].values())
    assert any(
        market["max_drawdown_delta_interval"][0] <= 0.0 or market["calmar_delta_interval"][0] <= 0.0
        for market in result["markets"].values()
    )
