from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest

_ROOT = Path(__file__).parents[1]
_ANALYSIS_PATH = (
    _ROOT / "reports" / "research" / "equal-weight-candidate-ensemble-vs-adaptive" / "analysis.py"
)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")
_CONFIG_PATH = _ROOT / "config" / "okx_research.json"

_spec = importlib.util.spec_from_file_location("equal_weight_candidate_ensemble", _ANALYSIS_PATH)
assert _spec is not None and _spec.loader is not None
analysis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analysis)


def _repository_candidate_position(prices: pd.Series) -> pd.Series:
    positions = []
    for candidate in analysis.candidate_grid():
        config = StrategyConfig(
            momentum_lookback=int(candidate["momentum_lookback"]),
            reversal_lookback=int(candidate["reversal_lookback"]),
            volatility_lookback=analysis.VOLATILITY_LOOKBACK,
            target_volatility=analysis.TARGET_VOLATILITY,
            max_abs_position=analysis.MAX_POSITION,
            min_position=analysis.MIN_POSITION,
            trend_weight=float(candidate["trend_weight"]),
            reversal_weight=float(candidate["reversal_weight"]),
            transaction_cost_bps=analysis.TRANSACTION_COST_BPS,
            annualization=analysis.ANNUALIZATION,
        )
        positions.append(run_backtest(prices, config).frame["position"])
    return pd.concat(positions, axis=1).mean(axis=1)


def test_equal_weight_position_matches_repository_candidates(btc_usdt_prices: pd.Series) -> None:
    observed = analysis.equal_weight_candidate_position(btc_usdt_prices)
    expected = _repository_candidate_position(btc_usdt_prices)

    assert len(analysis.candidate_grid()) == 27
    np.testing.assert_allclose(observed.to_numpy(), expected.to_numpy(), atol=1e-15, rtol=0.0)
    assert observed.between(0.0, 1.0).all()


def test_ensemble_recomputes_cash_entry_turnover_and_costs(
    btc_usdt_prices: pd.Series,
) -> None:
    evaluation_index = btc_usdt_prices.index[-40:]
    frame = analysis.build_ensemble_frame(btc_usdt_prices, evaluation_index)

    first = frame.iloc[0]
    assert first["turnover"] == pytest.approx(abs(first["position"]))
    assert first["trading_cost"] == pytest.approx(
        first["turnover"] * analysis.TRANSACTION_COST_BPS / 10_000.0
    )
    assert first["strategy_return"] == pytest.approx(
        first["position"] * first["asset_return"] - first["trading_cost"]
    )
    assert frame["turnover"].iloc[1:].to_numpy() == pytest.approx(
        frame["position"].diff().abs().iloc[1:].to_numpy()
    )


def test_noncircular_block_indices_are_seeded_and_contiguous() -> None:
    first = analysis.noncircular_block_indices(40, 7, np.random.default_rng(20260723))
    second = analysis.noncircular_block_indices(40, 7, np.random.default_rng(20260723))

    np.testing.assert_array_equal(first, second)
    assert len(first) == 40
    for start in range(0, len(first), 7):
        block = first[start : start + 7]
        if len(block) > 1:
            np.testing.assert_array_equal(np.diff(block), np.ones(len(block) - 1, dtype=int))


def test_ensemble_definition_matches_declared_repository_config() -> None:
    declared = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    strategy = declared["strategy"]
    search = declared["search"]

    assert tuple(search["momentum_lookbacks"]) == analysis.MOMENTUM_LOOKBACKS
    assert tuple(search["reversal_lookbacks"]) == analysis.REVERSAL_LOOKBACKS
    assert tuple(search["trend_weights"]) == analysis.TREND_WEIGHTS
    assert strategy["volatility_lookback"] == analysis.VOLATILITY_LOOKBACK
    assert strategy["target_volatility"] == analysis.TARGET_VOLATILITY
    assert strategy["max_abs_position"] == analysis.MAX_POSITION
    assert strategy["min_position"] == analysis.MIN_POSITION
    assert strategy["transaction_cost_bps"] == analysis.TRANSACTION_COST_BPS
    assert strategy["annualization"] == analysis.ANNUALIZATION

    expected = [
        {
            "momentum_lookback": momentum,
            "reversal_lookback": reversal,
            "trend_weight": weight,
            "reversal_weight": round(1.0 - weight, 10),
        }
        for momentum in search["momentum_lookbacks"]
        for reversal in search["reversal_lookbacks"]
        for weight in search["trend_weights"]
    ]
    assert analysis.candidate_grid() == expected


def test_result_records_complete_grid_candidate_accounting_and_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "rejected"
    assert result["canonical_signature"].startswith(
        "equal-weight-candidate-ensemble-vs-adaptive-v1|"
    )
    assert result["method"]["constituent_count"] == 27
    assert len(result["method"]["ensemble_constituents"]) == 27
    assert result["source"]["artifact_sha256"] == analysis.SOURCE_ARTIFACT_SHA256

    for market in analysis.MARKETS:
        market_result = result["markets"][market]
        assert market_result["observations"] == analysis.EXPECTED_OBSERVATIONS
        assert market_result["constituent_candidates"] == 27
        assert market_result["passes"] is False
        assert market_result["annualized_arithmetic_mean_delta_interval"]["lower"] <= 0.0
        assert market_result["annualized_sharpe_delta_interval"]["lower"] <= 0.0
        assert market_result["annualized_turnover_reduction"] > 0.0
