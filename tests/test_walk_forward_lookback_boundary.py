from __future__ import annotations

import pandas as pd
import pytest

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig, run_walk_forward_research


@pytest.mark.parametrize("reversal_lookback", [300, 301])
def test_walk_forward_rejects_reversal_lookbacks_without_selection_warmup(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    reversal_lookback: int,
) -> None:
    def unexpected_backtest(*_args: object, **_kwargs: object) -> None:
        pytest.fail("lookback validation must run before any candidate backtest")

    monkeypatch.setattr(walk_forward, "run_backtest", unexpected_backtest)

    with pytest.raises(
        ValueError,
        match="selection_bars must exceed every candidate lookback",
    ):
        run_walk_forward_research(
            btc_usdt_prices.iloc[:400],
            base_config=StrategyConfig(
                min_position=0.0,
                transaction_cost_bps=10.0,
                annualization=365,
            ),
            momentum_lookbacks=[21],
            reversal_lookbacks=[reversal_lookback],
            trend_weights=[0.7],
            selection_bars=300,
            test_bars=100,
            cost_multipliers=[1.0, 2.0],
        )
