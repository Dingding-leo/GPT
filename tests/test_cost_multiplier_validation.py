from __future__ import annotations

import pandas as pd
import pytest

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig


@pytest.mark.parametrize(
    "invalid_multiplier",
    [float("nan"), float("inf")],
    ids=["nan", "positive-infinity"],
)
def test_walk_forward_rejects_non_finite_cost_multipliers_before_backtest(
    btc_usdt_prices: pd.Series,
    invalid_multiplier: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_backtest(*_args: object, **_kwargs: object) -> None:
        pytest.fail("non-finite cost multipliers reached backtest evaluation")

    monkeypatch.setattr(walk_forward, "_run_test_window", unexpected_backtest)

    with pytest.raises(ValueError, match="cost multipliers must be finite and positive"):
        walk_forward.run_walk_forward_research(
            btc_usdt_prices.iloc[:400],
            base_config=StrategyConfig(
                min_position=0.0,
                transaction_cost_bps=5.0,
                annualization=252,
            ),
            momentum_lookbacks=[21],
            reversal_lookbacks=[3],
            trend_weights=[0.6],
            selection_bars=300,
            test_bars=100,
            cost_multipliers=[1.0, invalid_multiplier],
        )
