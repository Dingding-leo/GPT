from __future__ import annotations

import pandas as pd
import pytest

from gpt_quant.metrics import max_drawdown_from_returns, performance_metrics


def test_max_drawdown_known_path() -> None:
    returns = pd.Series([0.10, -0.20, 0.05])
    # NAV: 1.10 -> 0.88 -> 0.924, so the trough is -20% from the peak.
    assert max_drawdown_from_returns(returns) == pytest.approx(-0.20)


def test_first_observation_loss_counts_as_drawdown() -> None:
    assert max_drawdown_from_returns(pd.Series([-0.10, 0.05])) == pytest.approx(-0.10)


def test_metrics_are_finite_for_flat_returns() -> None:
    frame = pd.DataFrame(
        {
            "strategy_return": [0.0] * 30,
            "position": [0.0] * 30,
            "turnover": [0.0] * 30,
            "trading_cost": [0.0] * 30,
        }
    )
    metrics = performance_metrics(frame)
    assert metrics["sharpe"] == 0.0
    assert metrics["max_drawdown"] == 0.0
    assert metrics["total_return"] == 0.0
