from __future__ import annotations

import pandas as pd
import pytest

import gpt_quant.research as research_module
from gpt_quant import StrategyConfig, run_holdout_research


def _base_config() -> StrategyConfig:
    return StrategyConfig(
        min_position=0.0,
        transaction_cost_bps=10.0,
        annualization=365,
    )


def test_holdout_deduplicates_identical_candidate_formulas(
    btc_usdt_prices: pd.Series,
) -> None:
    result = run_holdout_research(
        btc_usdt_prices.iloc[:600],
        base_config=_base_config(),
        momentum_lookbacks=[21, 21, 42],
        reversal_lookbacks=[3, 3],
        trend_weights=[0.7, 0.7],
        top_candidates=10,
    )

    ranked_identities = {
        (
            entry["parameters"]["momentum_lookback"],
            entry["parameters"]["reversal_lookback"],
            entry["parameters"]["trend_weight"],
        )
        for entry in result.candidate_ranking
    }

    assert result.candidates_tested == 2
    assert len(result.candidate_ranking) == 2
    assert ranked_identities == {(21, 3, 0.7), (42, 3, 0.7)}


def test_holdout_deduplication_preserves_first_declared_order_for_score_ties(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(research_module, "_selection_score", lambda metrics: 1.0)

    result = run_holdout_research(
        btc_usdt_prices.iloc[:600],
        base_config=_base_config(),
        momentum_lookbacks=[42, 21, 42],
        reversal_lookbacks=[3, 3],
        trend_weights=[0.7, 0.7],
        top_candidates=10,
    )

    ranked_momentum = [
        entry["parameters"]["momentum_lookback"] for entry in result.candidate_ranking
    ]

    assert result.candidates_tested == 2
    assert ranked_momentum == [42, 21]
    assert result.selected_parameters["momentum_lookback"] == 42
