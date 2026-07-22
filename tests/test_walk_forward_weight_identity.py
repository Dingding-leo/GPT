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


def test_parameter_stability_preserves_exact_high_precision_weight_identity() -> None:
    selected = [
        {"momentum_lookback": 21, "reversal_lookback": 3, "trend_weight": 0.7},
        {
            "momentum_lookback": 21,
            "reversal_lookback": 3,
            "trend_weight": 0.70000000001,
        },
        {"momentum_lookback": 21, "reversal_lookback": 3, "trend_weight": 0.7},
    ]

    stability = walk_forward._parameter_stability(selected)

    assert stability["selection_frequency"] == {
        "m=21|r=3|trend=0.7000": 2,
        "m=21|r=3|trend=0.70000000001": 1,
    }
    assert stability["parameter_switches"] == 2
    assert stability["parameter_switch_rate"] == 1.0
    assert stability["unique_parameter_sets"] == 2
