from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gpt_quant.realized_edge_hysteresis import (
    FEE_ONE_WAY_BPS,
    INNOVATION_LOOKBACK,
    apply_target_innovation_hysteresis,
)

_REAL_OKX_FIXTURE = (
    Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT" / "okx-BTC-USDT-1H.csv"
)


def _canonical_structural_frame() -> pd.DataFrame:
    candles = pd.read_csv(_REAL_OKX_FIXTURE)
    asset_return = candles["close"].pct_change().fillna(0.0)
    position = np.array([0.0, 0.5, 0.5], dtype=float)
    turnover = np.array([0.0, 0.5, 0.0], dtype=float)
    trading_cost = turnover * FEE_ONE_WAY_BPS / 10_000.0
    return pd.DataFrame(
        {
            "timestamp": candles["timestamp"],
            "asset_return": asset_return,
            "position": position,
            "turnover": turnover,
            "trading_cost": trading_cost,
            "strategy_return": position * asset_return - trading_cost,
            "fold": 1,
        }
    )


def test_hysteresis_falls_back_deterministically_with_incomplete_real_history() -> None:
    frame = _canonical_structural_frame()
    first, first_diagnostics = apply_target_innovation_hysteresis(frame)
    second, second_diagnostics = apply_target_innovation_hysteresis(frame)

    pd.testing.assert_frame_equal(first, second)
    assert first_diagnostics == second_diagnostics
    assert first_diagnostics.fallback_decisions == len(frame)
    assert len(frame) < INNOVATION_LOOKBACK + 1
    np.testing.assert_allclose(first["hysteresis_position"], frame["position"], rtol=0, atol=0)
    np.testing.assert_allclose(
        first["hysteresis_trading_cost"],
        first["hysteresis_turnover"] * FEE_ONE_WAY_BPS / 10_000.0,
        rtol=0,
        atol=0,
    )


def test_hysteresis_rejects_gapped_or_non_five_bps_input() -> None:
    frame = _canonical_structural_frame()

    gapped = frame.drop(index=1).reset_index(drop=True)
    with pytest.raises(ValueError, match="continuous 1H grid"):
        apply_target_innovation_hysteresis(gapped)

    altered_cost = frame.copy()
    altered_cost.loc[1, "trading_cost"] += 1e-6
    with pytest.raises(ValueError, match="exactly 5 bps"):
        apply_target_innovation_hysteresis(altered_cost)
