from __future__ import annotations

import numpy as np
import pandas as pd

from scripts.run_candle_efficiency_state import _signed_efficiency, _stats, _tercile_effect


def _candles(rows: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


def test_signed_efficiency_is_bounded_and_zero_range_is_zero() -> None:
    candles = _candles(
        [
            (10.0, 12.0, 8.0, 12.0),
            (10.0, 10.0, 10.0, 10.0),
            (10.0, 11.0, 9.0, 9.0),
        ]
    )
    signed, zero_range = _signed_efficiency(candles)
    assert zero_range == 1
    assert signed.iloc[0] == 1.0
    assert signed.iloc[1] == 0.0
    assert signed.iloc[2] == -0.5
    assert signed.between(-1.0, 1.0).all()


def test_positive_affine_price_transform_preserves_efficiency() -> None:
    base = _candles(
        [
            (10.0, 12.0, 8.0, 12.0),
            (12.0, 13.0, 11.0, 11.5),
        ]
    )
    transformed = base * 7.0 + 3.0
    left, _ = _signed_efficiency(base)
    right, _ = _signed_efficiency(transformed)
    np.testing.assert_allclose(left.to_numpy(), right.to_numpy())


def test_tercile_effect_uses_only_ordered_observations() -> None:
    feature = np.arange(9, dtype=float)
    outcome = feature.copy()
    assert _tercile_effect(feature, outcome) == 6.0


def test_standardized_slope_and_rank_sign_match_monotone_signal() -> None:
    feature = np.arange(10, dtype=float)
    outcome = 2.0 * feature + 1.0
    rho, slope = _stats(feature, outcome)
    assert rho > 0
    assert slope > 0
