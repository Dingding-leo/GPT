from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).parents[1]
_ANALYSIS_PATH = (
    _ROOT
    / "reports"
    / "research"
    / "prior-fold-volatility-matched-es-vs-volatility-benchmark"
    / "analysis.py"
)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")
_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "okx_btc_usdt_prior_fold_volatility_scaling_20200111_20200209"
)

_spec = importlib.util.spec_from_file_location(
    "prior_fold_volatility_matched_es", _ANALYSIS_PATH
)
assert _spec is not None and _spec.loader is not None
analysis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analysis)


def test_prior_fold_scale_uses_only_previous_complete_fold() -> None:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    returns_path = _FIXTURE_DIR / "returns.csv"
    assert analysis.file_sha256(returns_path) == metadata["fixture_sha256"]
    frame = analysis.load_returns(returns_path, "BTC-USDT", verify_hash=False)
    original_size = analysis.COMPLETE_FOLD_SIZE
    analysis.COMPLETE_FOLD_SIZE = 10
    try:
        scaled, scales = analysis.prior_fold_scaled_returns(frame)
    finally:
        analysis.COMPLETE_FOLD_SIZE = original_size
    fold_one = frame.loc[frame["fold"] == 1]
    expected_scale = float(
        fold_one[analysis.STRATEGY_COLUMN].std(ddof=1)
        / fold_one[analysis.BENCHMARK_COLUMN].std(ddof=1)
    )

    assert scales[2] == pytest.approx(expected_scale)
    assert sorted(scaled["fold"].unique().tolist()) == [2, 3]
    assert len(scaled) == 20

    structurally_altered = frame.copy()
    structurally_altered.loc[
        structurally_altered["fold"] == 2, analysis.STRATEGY_COLUMN
    ] *= 9.0
    analysis.COMPLETE_FOLD_SIZE = 10
    try:
        _, altered_scales = analysis.prior_fold_scaled_returns(structurally_altered)
    finally:
        analysis.COMPLETE_FOLD_SIZE = original_size
    assert altered_scales[2] == pytest.approx(scales[2])
    assert altered_scales[3] != pytest.approx(scales[3])


def test_fold_validation_rejects_oversized_trailing_fold() -> None:
    frame = analysis.load_returns(
        _FIXTURE_DIR / "returns.csv", "BTC-USDT", verify_hash=False
    )
    original_size = analysis.COMPLETE_FOLD_SIZE
    analysis.COMPLETE_FOLD_SIZE = 10
    extra = frame.iloc[[-1]].copy()
    extra["timestamp"] = extra["timestamp"] + pd.Timedelta(days=1)
    extra["fold"] = 3
    oversized = pd.concat([frame, extra], ignore_index=True)

    try:
        with pytest.raises(
            ValueError, match="trailing incomplete fold must be shorter"
        ):
            analysis.complete_folds(oversized)
    finally:
        analysis.COMPLETE_FOLD_SIZE = original_size


def test_result_records_complete_candidate_accounting_and_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "rejected"
    assert (
        result["method"]["first_complete_fold"]
        == "used only to estimate fold-2 scale"
    )
    assert result["method"]["trailing_short_fold"] == "excluded"
    assert result["source"]["artifact_sha256"] == (
        "8c89b8ecc4904cba018ac95079305c46e25d92199242b95d3aeffaad1bc0799c"
    )
    for market in analysis.MARKETS:
        market_result = result["markets"][market]
        assert market_result["evaluation_observations"] == 2250
        assert market_result["evaluation_folds"] == list(range(2, 27))
        assert market_result["excluded_folds"] == [1, 27]
        assert market_result["passes"] is False
        assert np.isfinite(market_result["delta"])
        assert market_result["confidence_interval"]["lower"] <= 0.0
