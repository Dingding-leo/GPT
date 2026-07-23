from __future__ import annotations

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest
from gpt_quant.metrics import performance_metrics


def _insolvent_cost_config() -> StrategyConfig:
    return StrategyConfig(
        momentum_lookback=2,
        reversal_lookback=1,
        volatility_lookback=2,
        target_volatility=2.0,
        trend_weight=1.0,
        reversal_weight=0.0,
        transaction_cost_bps=20_000.0,
        annualization=365,
    )


def test_performance_metrics_rejects_insolvent_real_backtest(
    btc_usdt_prices: pd.Series,
) -> None:
    result = run_backtest(
        btc_usdt_prices.iloc[:50],
        _insolvent_cost_config(),
    )
    assert result.frame["strategy_return"].le(-1.0).any()

    with pytest.raises(ValueError, match="insolvency occurs"):
        performance_metrics(result)


def test_metrics_before_future_insolvency_remain_valid(
    btc_usdt_prices: pd.Series,
) -> None:
    result = run_backtest(
        btc_usdt_prices.iloc[:50],
        _insolvent_cost_config(),
    )
    prefix = result.frame.iloc[:3].copy()
    assert result.frame["strategy_return"].iloc[3:].le(-1.0).any()

    metrics = performance_metrics(prefix, annualization=365)

    assert metrics["observations"] == 3
    assert metrics["total_return"] == pytest.approx(0.0)


def test_performance_metrics_rejects_insolvent_repriced_frame(
    btc_usdt_prices: pd.Series,
) -> None:
    frame = run_backtest(
        btc_usdt_prices.iloc[:100],
        StrategyConfig(),
    ).frame.copy()
    frame.at[frame.index[-1], "strategy_return"] = -1.0

    with pytest.raises(ValueError, match="insolvency occurs"):
        performance_metrics(frame, annualization=365)
