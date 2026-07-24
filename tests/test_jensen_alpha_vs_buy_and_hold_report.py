from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "reports" / "research" / "jensen-alpha-vs-buy-and-hold" / "analysis.py"
RESULT_PATH = ROOT / "reports" / "research" / "jensen-alpha-vs-buy-and-hold" / "result.json"
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "okx_btc_usdt_oos_returns_20200111_20200219.csv"

SPEC = importlib.util.spec_from_file_location("jensen_alpha_analysis", ANALYSIS_PATH)
assert SPEC is not None and SPEC.loader is not None
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def test_jensen_alpha_matches_independent_real_return_calculation() -> None:
    frame = pd.read_csv(FIXTURE_PATH)
    strategy = frame["strategy_return"].to_numpy(dtype=float)
    benchmark = frame["benchmark_buy_and_hold_return"].to_numpy(dtype=float)

    beta = np.cov(benchmark, strategy, ddof=1)[0, 1] / np.var(benchmark, ddof=1)
    expected_alpha = float((np.mean(strategy) - beta * np.mean(benchmark)) * 365)

    actual_alpha, actual_beta = analysis.annualized_jensen_alpha(strategy, benchmark)

    assert actual_alpha == pytest.approx(expected_alpha, abs=1e-15)
    assert actual_beta == pytest.approx(beta, abs=1e-15)


def test_moving_blocks_are_seeded_contiguous_and_noncircular() -> None:
    first = analysis.moving_block_indices(40, 7, np.random.default_rng(20260723))
    second = analysis.moving_block_indices(40, 7, np.random.default_rng(20260723))

    np.testing.assert_array_equal(first, second)
    assert len(first) == 40
    assert np.all((first >= 0) & (first < 40))

    for start in range(0, 35, 7):
        block = first[start : start + 7]
        if len(block) > 1:
            np.testing.assert_array_equal(np.diff(block), np.ones(len(block) - 1))


def test_committed_result_records_single_rejected_candidate_and_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["source"]["artifact_sha256"] == (
        "e5654461e56bd76f7b61133a4eb9b00b7e98974fc8a09449185614250d462344"
    )
    assert result["source"]["merged_main_sha"] == ("2a8b0ada66a5b2271ebaf1a92f520caa211bf619")

    for market, expected_hash in {
        "BTC-USDT": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "ETH-USDT": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
    }.items():
        market_result = result["markets"][market]
        assert market_result["observations"] == 2340
        assert market_result["returns_sha256"] == expected_hash
        assert market_result["passes"] is False
        assert market_result["alpha_confidence_interval"]["lower"] <= 0.0
