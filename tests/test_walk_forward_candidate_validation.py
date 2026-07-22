from __future__ import annotations

import pandas as pd
import pytest

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig, run_walk_forward_research


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("momentum_lookbacks", 21.5, "momentum lookback candidates must be integers"),
        ("momentum_lookbacks", True, "momentum lookback candidates must be integers"),
        ("momentum_lookbacks", "21", "momentum lookback candidates must be integers"),
        ("momentum_lookbacks", 1, "momentum lookback candidates must be at least 2"),
        ("reversal_lookbacks", 3.5, "reversal lookback candidates must be integers"),
        ("reversal_lookbacks", False, "reversal lookback candidates must be integers"),
        ("reversal_lookbacks", "3", "reversal lookback candidates must be integers"),
        ("reversal_lookbacks", 0, "reversal lookback candidates must be at least 1"),
        ("trend_weights", "0.7", "trend weight candidates must be finite real numbers"),
        ("trend_weights", True, "trend weight candidates must be finite real numbers"),
        ("trend_weights", float("nan"), "trend weight candidates must be finite real numbers"),
        ("trend_weights", float("inf"), "trend weight candidates must be finite real numbers"),
    ],
)
def test_walk_forward_rejects_coerced_candidates_before_backtesting(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    def unexpected_backtest(*args: object, **kwargs: object) -> None:
        pytest.fail("candidate validation must run before any backtest")

    monkeypatch.setattr(walk_forward, "run_backtest", unexpected_backtest)
    candidate_grid: dict[str, list[object]] = {
        "momentum_lookbacks": [21],
        "reversal_lookbacks": [3],
        "trend_weights": [0.7],
    }
    candidate_grid[field] = [value]

    with pytest.raises(ValueError, match=message):
        run_walk_forward_research(
            btc_usdt_prices.iloc[:400],
            base_config=StrategyConfig(
                min_position=0.0,
                transaction_cost_bps=10.0,
                annualization=365,
            ),
            selection_bars=300,
            test_bars=100,
            cost_multipliers=[1.0, 2.0],
            **candidate_grid,
        )


def test_candidate_grid_preserves_valid_values_without_coercion() -> None:
    candidates = walk_forward._candidates(
        StrategyConfig(min_position=0.0),
        momentum=[21, 63],
        reversal=[3],
        trend_weights=[0.6, 0.8],
    )

    assert [
        (
            candidate.momentum_lookback,
            candidate.reversal_lookback,
            candidate.trend_weight,
            candidate.reversal_weight,
        )
        for candidate in candidates
    ] == [
        (21, 3, 0.6, 0.4),
        (21, 3, 0.8, 0.2),
        (63, 3, 0.6, 0.4),
        (63, 3, 0.8, 0.2),
    ]
