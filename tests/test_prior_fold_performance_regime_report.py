from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

_SCRIPT_PATH = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "prior-fold-performance-regimes"
    / "analysis.py"
)
_SCRIPT_SPEC = importlib.util.spec_from_file_location(
    "prior_fold_performance_analysis", _SCRIPT_PATH
)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"unable to load research analysis from {_SCRIPT_PATH}")
analysis = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(analysis)

_RESULT_PATH = _SCRIPT_PATH.with_name("result.json")


def _real_complete_fold_records(prices: pd.Series) -> list[dict[str, object]]:
    observed_returns = prices.pct_change().dropna().iloc[: 9 * analysis.EXPECTED_TEST_BARS]
    assert len(observed_returns) == 9 * analysis.EXPECTED_TEST_BARS
    records = []
    for fold_index in range(9):
        start = fold_index * analysis.EXPECTED_TEST_BARS
        stop = start + analysis.EXPECTED_TEST_BARS
        fold_returns = observed_returns.iloc[start:stop].to_numpy(dtype=float)
        records.append(
            {
                "fold": fold_index + 1,
                "strategy_returns": fold_returns,
                "total_return": analysis.compounded_return(fold_returns),
            }
        )
    return records


def test_previous_fold_regimes_use_only_observed_prior_fold(
    btc_usdt_prices: pd.Series,
) -> None:
    records = _real_complete_fold_records(btc_usdt_prices)
    classified = analysis.classify_by_previous_fold(records)

    expected_labels = [
        analysis.compounded_return(np.asarray(record["strategy_returns"], dtype=float)) > 0.0
        for record in records[:-1]
    ]
    assert [record["previous_fold_positive"] for record in classified] == expected_labels
    assert [record["fold"] for record in classified] == list(range(2, 10))
    assert {record["previous_fold_positive"] for record in classified} == {False, True}


def test_conditional_means_match_independent_real_return_calculation(
    btc_usdt_prices: pd.Series,
) -> None:
    records = _real_complete_fold_records(btc_usdt_prices)
    classified = analysis.classify_by_previous_fold(records)
    observed = analysis.conditional_annualized_means(classified)

    for positive, regime in ((True, "previous_positive"), (False, "previous_nonpositive")):
        selected = np.concatenate(
            [
                np.asarray(current["strategy_returns"], dtype=float)
                for previous, current in zip(records[:-1], records[1:], strict=True)
                if (
                    np.prod(1.0 + np.asarray(previous["strategy_returns"], dtype=float)) - 1.0
                    > 0.0
                )
                == positive
            ]
        )
        assert observed[regime] == float(selected.mean() * analysis.ANNUALIZATION)


def test_fold_block_resampling_is_deterministic_and_contiguous() -> None:
    first = analysis.moving_block_indices(9, block_length=3, resamples=8, seed=20260722)
    second = analysis.moving_block_indices(9, block_length=3, resamples=8, seed=20260722)

    np.testing.assert_array_equal(first, second)
    assert first.shape == (8, 9)
    for sample in first:
        for start in range(0, len(sample), 3):
            np.testing.assert_array_equal(np.diff(sample[start : start + 3]), np.ones(2, dtype=int))


def test_committed_result_records_complete_rejected_candidate() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.SIGNATURE
    assert result["candidate_count"] == 1
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["verdict"] == "reject"
    assert result["verdict"] == "reject"
    assert len(result["failure_reasons"]) == 4
    assert result["provenance"]["provider"] == "OKX"
    assert result["provenance"]["timeframe"] == "1Dutc"
    assert result["provenance"]["source_artifact_sha256"] == (
        "9955cfa0f2faefeddf8cb63e3fcf4765e0ccbd32c4c866824733c93ed4160e9c"
    )
    assert result["provenance"]["candidate_grid_size"] == 27
    assert result["provenance"]["transaction_cost_bps"] == 10.0
    assert result["provenance"]["execution_delay_bars"] == 1
    for market in analysis.MARKETS:
        market_result = result["markets"][market]
        assert market_result["complete_folds"] == 26
        assert market_result["classified_folds"] == 25
        assert market_result["excluded_folds"] == 1
        assert market_result["passes"] is False
        assert sum(regime["folds"] for regime in market_result["regimes"].values()) == 25
        assert all(regime["passes"] is False for regime in market_result["regimes"].values())
