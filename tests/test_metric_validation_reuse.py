from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

import gpt_quant.metrics as metrics_module
from gpt_quant import StrategyConfig, run_backtest
from gpt_quant.metrics import (
    _max_drawdown_from_validated_values,
    _validated_returns,
    max_drawdown_from_returns,
    performance_metrics,
)


def test_validated_drawdown_reuse_preserves_real_okx_metrics(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
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
    original_values = values.copy()

    oracle_nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    oracle_drawdown = oracle_nav / np.maximum.accumulate(oracle_nav) - 1.0
    expected = float(oracle_drawdown.min())
    reused = _max_drawdown_from_validated_values(values)
    public = max_drawdown_from_returns(result.frame["strategy_return"])

    def reject_duplicate_public_validation(_returns: pd.Series) -> float:
        raise AssertionError("performance_metrics repeated the public drawdown validation path")

    monkeypatch.setattr(
        metrics_module,
        "max_drawdown_from_returns",
        reject_duplicate_public_validation,
    )
    calculated = performance_metrics(result)

    assert np.shares_memory(values, returns.to_numpy(copy=False))
    np.testing.assert_array_equal(values, original_values)
    assert reused == expected
    assert public == expected
    assert calculated["max_drawdown"] == expected
