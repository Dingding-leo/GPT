from __future__ import annotations

import numpy as np
import pytest

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig


def test_candidate_grid_preserves_numpy_numeric_scalars() -> None:
    candidates = walk_forward._candidates(
        StrategyConfig(min_position=0.0),
        momentum=np.array([21, 63], dtype=np.int64),
        reversal=np.array([3], dtype=np.int32),
        trend_weights=np.array([0.6, 0.8], dtype=np.float64),
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
    assert all(type(candidate.momentum_lookback) is int for candidate in candidates)
    assert all(type(candidate.reversal_lookback) is int for candidate in candidates)
    assert all(type(candidate.trend_weight) is float for candidate in candidates)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("momentum", "momentum lookback candidates must be integers"),
        ("reversal", "reversal lookback candidates must be integers"),
        ("trend_weights", "trend weight candidates must be finite real numbers"),
    ],
)
def test_candidate_grid_rejects_numpy_boolean_scalars(field: str, message: str) -> None:
    grid: dict[str, object] = {
        "momentum": [21],
        "reversal": [3],
        "trend_weights": [0.7],
    }
    grid[field] = [np.bool_(True)]

    with pytest.raises(ValueError, match=message):
        walk_forward._candidates(
            StrategyConfig(min_position=0.0),
            momentum=grid["momentum"],
            reversal=grid["reversal"],
            trend_weights=grid["trend_weights"],
        )
