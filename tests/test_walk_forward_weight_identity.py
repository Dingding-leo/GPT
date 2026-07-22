from __future__ import annotations

import pandas as pd

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig, run_walk_forward_research


def test_walk_forward_preserves_distinct_high_precision_weights(
    btc_usdt_prices: pd.Series,
) -> None:
    weights = [0.7, 0.70000000001]
    base = StrategyConfig(
        min_position=0.0,
        transaction_cost_bps=10.0,
        annualization=365,
    )

    candidates = walk_forward._candidates(
        base,
        momentum=[21],
        reversal=[3],
        trend_weights=weights,
    )

    assert [candidate.trend_weight for candidate in candidates] == weights
    assert len(candidates) == 2

    result = run_walk_forward_research(
        btc_usdt_prices.iloc[:400],
        base_config=base,
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=weights,
        selection_bars=300,
        test_bars=100,
        cost_multipliers=[1.0, 2.0],
    )

    assert result.settings["candidate_count"] == 2
    assert result.folds[0]["candidates_tested"] == 2
