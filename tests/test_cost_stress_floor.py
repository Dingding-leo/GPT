from __future__ import annotations

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_walk_forward_research


def test_walk_forward_always_runs_exact_two_x_cost_stress(
    btc_usdt_prices: pd.Series,
) -> None:
    result = run_walk_forward_research(
        btc_usdt_prices.iloc[:700],
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=365,
        ),
        momentum_lookbacks=[63],
        reversal_lookbacks=[3],
        trend_weights=[0.7],
        selection_bars=300,
        test_bars=100,
        cost_multipliers=[1.0],
    )
    one_x = result.cost_stress_metrics["1x"]
    two_x = result.cost_stress_metrics["2x"]

    assert result.settings["cost_multipliers"] == [1.0, 2.0]
    assert set(result.cost_stress_metrics) == {"1x", "2x"}
    assert one_x["cost_drag_sum"] > 0.0
    assert two_x["cost_drag_sum"] == pytest.approx(2.0 * one_x["cost_drag_sum"])
    assert two_x["total_return"] <= one_x["total_return"]
