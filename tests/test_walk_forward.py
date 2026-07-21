from __future__ import annotations

import pandas as pd

from gpt_quant import StrategyConfig, generate_regime_prices, run_walk_forward_research


def _run(prices: pd.Series):
    return run_walk_forward_research(
        prices,
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=252,
        ),
        momentum_lookbacks=[21, 63],
        reversal_lookbacks=[3],
        trend_weights=[0.6, 0.8],
        selection_bars=300,
        test_bars=100,
        cost_multipliers=[1.0, 2.0, 4.0],
    )


def test_walk_forward_folds_are_non_overlapping_and_charge_boundary_turnover() -> None:
    result = _run(generate_regime_prices(rows=700, seed=23))

    assert len(result.folds) == 4
    assert not result.combined_frame.index.duplicated().any()
    assert result.combined_frame["position"].min() >= 0.0
    assert all(fold["selection_end"] < fold["test_start"] for fold in result.folds)

    previous_position = 0.0
    for fold_number in range(1, len(result.folds) + 1):
        frame = result.combined_frame.loc[result.combined_frame["fold"] == fold_number]
        expected = abs(float(frame["position"].iloc[0]) - previous_position)
        assert frame["turnover"].iloc[0] == expected
        previous_position = float(frame["position"].iloc[-1])

    assert (
        result.cost_stress_metrics["4x"]["total_return"]
        <= result.cost_stress_metrics["1x"]["total_return"]
    )


def test_future_price_change_cannot_rewrite_prior_walk_forward_results() -> None:
    prices = generate_regime_prices(rows=700, seed=29)
    original = _run(prices)
    changed_prices = prices.copy()
    changed_prices.iloc[-1] *= 1.75
    changed = _run(changed_prices)

    cutoff = prices.index[-2]
    columns = ["position", "turnover", "trading_cost", "strategy_return", "fold"]
    pd.testing.assert_frame_equal(
        original.combined_frame.loc[:cutoff, columns],
        changed.combined_frame.loc[:cutoff, columns],
    )
