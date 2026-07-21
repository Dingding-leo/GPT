from __future__ import annotations

import math

import pytest

from gpt_quant import StrategyConfig


@pytest.mark.parametrize("transaction_cost_bps", [math.nan, math.inf, -math.inf])
def test_strategy_config_rejects_non_finite_transaction_costs(
    transaction_cost_bps: float,
) -> None:
    with pytest.raises(ValueError, match="finite and non-negative"):
        StrategyConfig(transaction_cost_bps=transaction_cost_bps)
