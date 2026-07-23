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

_spec = importlib.util.spec_from_file_location("prior_fold_volatility_matched_es", _ANALYSIS_PATH)
assert _spec is not None and _spec.loader is not None
analysis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analysis)


def _fixture_inputs() -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    returns_path = _FIXTURE_DIR / "returns.csv"
    snapshot_path = _FIXTURE_DIR / "snapshot.csv"
    assert analysis.file_sha256(returns_path) == metadata["returns_fixture_sha256"]
    assert analysis.file_sha256(snapshot_path) == metadata["snapshot_fixture_sha256"]
    returns = analysis.load_returns(returns_path, "BTC-USDT", verify_hash=False)
    snapshot = analysis.load_snapshot(snapshot_path, "BTC-USDT", verify_hash=False)
    return returns, snapshot, metadata


def test_prior_fold_scale_reconstructs_position_and_costs_from_real_snapshot() -> None:
    frame, snapshot, _ = _fixture_inputs()
    benchmark, reconstruction_error = analysis.reconstruct_volatility_benchmark(snapshot, frame)
    assert reconstruction_error < 1e-15

    original_size = analysis.COMPLETE_FOLD_SIZE
    analysis.COMPLETE_FOLD_SIZE = 10
    try:
        scaled, scales = analysis.prior_fold_scaled_returns(frame, benchmark)
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

    first = scaled.iloc[0]
    assert first["scaled_benchmark_turnover"] == pytest.approx(
        abs(first["scaled_benchmark_position"])
    )
    fold_three_first = scaled.loc[scaled["fold"] == 3].iloc[0]
    linearly_scaled_net_return = (
        fold_three_first[analysis.BENCHMARK_COLUMN] * fold_three_first["prior_fold_scale"]
    )
    assert fold_three_first["scaled_benchmark_return"] != pytest.approx(
        linearly_scaled_net_return,
        abs=1e-8,
    )

    structurally_altered = frame.copy()
    structurally_altered.loc[
        structurally_altered["fold"] == 2, analysis.STRATEGY_COLUMN
    ] *= 2.0
    analysis.COMPLETE_FOLD_SIZE = 10
    try:
        _, altered_scales = analysis.prior_fold_scaled_returns(
            structurally_altered,
            benchmark,
        )
    finally:
        analysis.COMPLETE_FOLD_SIZE = original_size
    assert altered_scales[2] == pytest.approx(scales[2])
    assert altered_scales[3] != pytest.approx(scales[3])


def test_fold_validation_rejects_oversized_trailing_fold() -> None:
    frame, _, _ = _fixture_inputs()
    original_size = analysis.COMPLETE_FOLD_SIZE
    analysis.COMPLETE_FOLD_SIZE = 10
    extra = frame.iloc[[-1]].copy()
    extra["timestamp"] = extra["timestamp"] + pd.Timedelta(days=1)
    extra["fold"] = 3
    oversized = pd.concat([frame, extra], ignore_index=True)

    try:
        with pytest.raises(ValueError, match="trailing incomplete fold must be shorter"):
            analysis.complete_folds(oversized)
    finally:
        analysis.COMPLETE_FOLD_SIZE = original_size


def test_result_records_cost_reconstruction_candidate_accounting_and_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "rejected"
    assert result["canonical_signature"].startswith(
        "prior-fold-volatility-matched-expected-shortfall-vs-volatility-benchmark-v2|"
    )
    assert "cost-recomputed" in result["canonical_signature"]
    assert result["method"]["first_complete_fold"] == "used only to estimate fold-2 scale"
    assert result["method"]["trailing_short_fold"] == "excluded"
    assert "turnover and costs recomputed" in result["method"]["scaled_execution"]
    assert result["source"]["artifact_sha256"] == (
        "8c89b8ecc4904cba018ac95079305c46e25d92199242b95d3aeffaad1bc0799c"
    )
    for market in analysis.MARKETS:
        market_result = result["markets"][market]
        assert market_result["evaluation_observations"] == 2250
        assert market_result["evaluation_folds"] == list(range(2, 27))
        assert market_result["excluded_folds"] == [1, 27]
        assert market_result["benchmark_reconstruction_max_abs_error"] < 1e-15
        assert market_result["scaled_benchmark_total_turnover"] > 0.0
        assert 0.0 <= market_result["scaled_benchmark_max_position"] <= 1.0
        assert market_result["passes"] is False
        assert np.isfinite(market_result["delta"])
        assert market_result["confidence_interval"]["lower"] <= 0.0
