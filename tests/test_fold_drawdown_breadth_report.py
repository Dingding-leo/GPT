from __future__ import annotations

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
    / "fold-drawdown-breadth"
    / "analysis.py"
)
RESULT_PATH = (
    REPOSITORY_ROOT
    / "reports"
    / "research"
    / "fold-drawdown-breadth"
    / "result.json"
)
FIXTURE_PATH = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "okx"
    / "btc_eth_oos_20200111_20200219"
    / "btc_usdt_returns.csv"
)

SPEC = importlib.util.spec_from_file_location("fold_drawdown_breadth_analysis", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def test_maximum_drawdown_matches_independent_real_okx_calculation() -> None:
    fixture = pd.read_csv(FIXTURE_PATH)
    returns = fixture["strategy_return"].to_numpy(dtype=float)
    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    expected = float(np.min(equity / np.maximum.accumulate(equity) - 1.0))

    assert analysis.maximum_drawdown(returns) == pytest.approx(expected, rel=0, abs=1e-15)


def test_committed_result_is_reproducible_from_persisted_fold_statistics() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 1, "rejected": 0}
    assert result["verdict"] == "pass"
    assert result["provenance"]["source_artifact_sha256"] == (
        "30523ece44c47c7c3317f7a5f5e6273eb5886cccb213dae2cc177b86dce007df"
    )

    for market in analysis.MARKETS:
        statistics = result["markets"][market]
        strategy = np.asarray(statistics["strategy_fold_max_drawdowns"], dtype=float)
        benchmark = np.asarray(statistics["benchmark_fold_max_drawdowns"], dtype=float)
        reductions = np.asarray(statistics["fold_drawdown_reductions"], dtype=float)

        np.testing.assert_allclose(reductions, strategy - benchmark, rtol=0, atol=1e-15)
        recomputed = analysis.moving_block_mean_reduction(
            reductions,
            block_length=analysis.BLOCK_LENGTH_FOLDS,
            resamples=analysis.RESAMPLES,
            confidence=analysis.CONFIDENCE,
            seed=analysis.SEEDS[market],
        )
        for key in (
            "mean_drawdown_reduction",
            "median_drawdown_reduction",
            "confidence_lower",
            "confidence_upper",
            "probability_mean_reduction_positive",
        ):
            assert statistics[key] == pytest.approx(recomputed[key], rel=0, abs=1e-15)
        assert statistics["positive_reduction_folds"] == 26
        assert statistics["confidence_lower"] > 0.0
