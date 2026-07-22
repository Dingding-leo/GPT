from __future__ import annotations

import json
from decimal import Decimal

import numpy as np
import pytest

from gpt_quant import StrategyConfig


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("momentum_lookback", 63.0),
        ("momentum_lookback", "63"),
        ("reversal_lookback", True),
        ("volatility_lookback", np.bool_(True)),
        ("annualization", np.float64(365.0)),
    ],
)
def test_strategy_config_rejects_non_integral_timing_controls(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError, match=rf"{field} must be an integer"):
        StrategyConfig(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_volatility", True),
        ("max_abs_position", np.bool_(True)),
        ("min_position", "0"),
        ("trend_weight", False),
        ("reversal_weight", "0.3"),
        ("transaction_cost_bps", np.bool_(False)),
    ],
)
def test_strategy_config_rejects_non_real_risk_and_cost_controls(
    field: str,
    value: object,
) -> None:
    with pytest.raises(ValueError):
        StrategyConfig(**{field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_volatility", Decimal("2.000000000000000000000001")),
        ("max_abs_position", Decimal("10.000000000000000000000001")),
        ("min_position", Decimal("1.000000000000000000000001")),
        ("trend_weight", Decimal("-1e-1000")),
        ("transaction_cost_bps", Decimal("-1e-1000")),
    ],
)
def test_strategy_config_rejects_decimal_values_that_cross_exact_bounds(
    field: str,
    value: Decimal,
) -> None:
    with pytest.raises(ValueError):
        StrategyConfig(**{field: value})


def test_strategy_config_normalizes_supported_numeric_scalars() -> None:
    config = StrategyConfig(
        momentum_lookback=np.int64(90),
        reversal_lookback=np.int32(5),
        volatility_lookback=np.int64(30),
        target_volatility=Decimal("0.5"),
        max_abs_position=np.float64(1.0),
        min_position=np.float32(0.0),
        trend_weight=np.float64(0.7),
        reversal_weight=Decimal("0.3"),
        transaction_cost_bps=Decimal("10.0"),
        annualization=np.int32(365),
    )

    values = config.to_dict()
    for field in (
        "momentum_lookback",
        "reversal_lookback",
        "volatility_lookback",
        "annualization",
    ):
        assert type(values[field]) is int
    for field in (
        "target_volatility",
        "max_abs_position",
        "min_position",
        "trend_weight",
        "reversal_weight",
        "transaction_cost_bps",
    ):
        assert type(values[field]) is float

    json.dumps(values, allow_nan=False)
