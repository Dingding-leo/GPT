from __future__ import annotations

import math

import pytest

from gpt_quant import StrategyConfig


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("trend_weight", math.nan),
        ("trend_weight", math.inf),
        ("trend_weight", -math.inf),
        ("reversal_weight", math.nan),
        ("reversal_weight", math.inf),
        ("reversal_weight", -math.inf),
    ],
)
def test_strategy_config_rejects_non_finite_signal_weights(
    field: str,
    value: float,
) -> None:
    with pytest.raises(ValueError, match="signal weights must be finite"):
        StrategyConfig(**{field: value})


def test_strategy_config_preserves_finite_single_signal_weights() -> None:
    config = StrategyConfig(trend_weight=0.0, reversal_weight=1.0)

    assert config.normalized_weights() == (0.0, 1.0)
