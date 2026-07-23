from __future__ import annotations

import numpy as np
import pandas as pd

from gpt_quant import StrategyConfig, run_backtest
from gpt_quant.metrics import (
    _max_drawdown_from_validated_values,
    _validated_returns,
    max_drawdown_from_returns,
    performance_metrics,
)


def test_validated_drawdown_reuse_preserves_real_okx_metrics(
    btc_usdt_prices: pd.Series,
) -> None:
    result = run_backtest(
        btc_usdt_prices,
        StrategyConfig(
            momentum_lookback=90,
            reversal_lookback=5,
            volatility_lookback=20,
            target_volatility=0.25,
            max_abs_position=1.0,
            min_position=0.0,
            trend_weight=0.7,
            reversal_weight=0.3,
            transaction_cost_bps=5.0,
            annualization=365,
        ),
    )
    returns = _validated_returns(result.frame["strategy_return"])
    values = returns.to_numpy(copy=False)

    reused = _max_drawdown_from_validated_values(values)
    public = max_drawdown_from_returns(result.frame["strategy_return"])
    metrics = performance_metrics(result)

    assert np.shares_memory(values, returns.to_numpy(copy=False))
    assert reused == public
    assert metrics["max_drawdown"] == reused
