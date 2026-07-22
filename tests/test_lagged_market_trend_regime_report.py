from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

_ANALYSIS_PATH = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "lagged-market-trend-regimes"
    / "analysis.py"
)
_SPEC = importlib.util.spec_from_file_location("lagged_market_trend_regimes", _ANALYSIS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis from {_ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")


def test_lagged_trend_labels_use_only_prior_real_okx_observations(
    btc_usdt_prices: pd.Series,
) -> None:
    asset_returns = btc_usdt_prices.pct_change().fillna(0.0).to_numpy(dtype=float)
    labels = analysis.lagged_trend_labels(asset_returns)

    assert np.all(labels[: analysis.TREND_LOOKBACK] == "warmup")
    for index in range(analysis.TREND_LOOKBACK, len(asset_returns)):
        denominator_index = max(0, index - analysis.TREND_LOOKBACK - 1)
        prior_growth = (
            btc_usdt_prices.iloc[index - 1] / btc_usdt_prices.iloc[denominator_index] - 1.0
        )
        expected = "positive_trend" if prior_growth > 0.0 else "nonpositive_trend"
        assert labels[index] == expected


def test_moving_blocks_preserve_contiguous_real_observation_order(
    btc_usdt_prices: pd.Series,
) -> None:
    indices = analysis.moving_block_indices(
        len(btc_usdt_prices),
        block_length=analysis.BLOCK_LENGTH,
        resamples=4,
        seed=20260722,
    )

    assert indices.shape == (4, len(btc_usdt_prices))
    for sample in indices:
        for start in range(0, len(sample), analysis.BLOCK_LENGTH):
            block = sample[start : start + analysis.BLOCK_LENGTH]
            assert np.all(np.diff(block) == 1)


def test_persisted_result_records_single_rejected_candidate() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.SIGNATURE
    assert result["candidate_count"] == 1
    assert len(result["candidates"]) == 1
    assert result["verdict"] == "reject"
    assert result["candidates"][0]["verdict"] == "reject"
    assert len(result["failure_reasons"]) == 4
    assert result["provenance"]["source_artifact_sha256"] == (
        "9dd429dfab4e7644b7b7e1113ea1dcd7dfbcde5968974ed64e3ef176597dd73d"
    )
    for market in analysis.MARKETS:
        market_result = result["markets"][market]
        assert market_result["warmup_observations"] == analysis.TREND_LOOKBACK
        assert market_result["eligible_observations"] == 2250
        for regime in ("positive_trend", "nonpositive_trend"):
            values = market_result["regimes"][regime]
            assert values["confidence_interval"]["lower"] <= 0.0
            assert values["passes"] is False
