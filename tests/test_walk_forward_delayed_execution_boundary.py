from __future__ import annotations

import pandas as pd
import pytest

from gpt_quant import StrategyConfig
from gpt_quant.backtest import run_backtest

_SELECTION_BARS = 300
_LOOKBACK_DIMENSIONS = ("momentum", "reversal", "volatility")


def _boundary_config(*, dimension: str, lookback: int) -> StrategyConfig:
    values = {
        "momentum_lookback": 21,
        "reversal_lookback": 5,
        "volatility_lookback": 20,
    }
    key = f"{dimension}_lookback"
    if key not in values:
        raise AssertionError(f"unsupported lookback dimension: {dimension}")
    values[key] = lookback
    return StrategyConfig(
        **values,
        min_position=-1.0,
        transaction_cost_bps=10.0,
        annualization=365,
    )


@pytest.mark.parametrize("dimension", _LOOKBACK_DIMENSIONS)
def test_walk_forward_warmup_boundary_matches_delayed_execution(
    btc_usdt_prices: pd.Series,
    dimension: str,
) -> None:
    prices = btc_usdt_prices.iloc[:_SELECTION_BARS]

    last_executable = run_backtest(
        prices,
        _boundary_config(
            dimension=dimension,
            lookback=_SELECTION_BARS - 2,
        ),
    ).frame
    underwarmed = run_backtest(
        prices,
        _boundary_config(
            dimension=dimension,
            lookback=_SELECTION_BARS - 1,
        ),
    ).frame

    # Allow both position signs so a fully formed real-data signal cannot be
    # clipped to cash; this regression checks timing, not spot-strategy results.
    assert last_executable["target_position"].iloc[:-2].eq(0.0).all()
    assert last_executable["target_position"].iloc[-2] != 0.0
    assert last_executable["position"].iloc[:-1].eq(0.0).all()
    assert last_executable["position"].iloc[-1] == pytest.approx(
        last_executable["target_position"].iloc[-2]
    )

    assert underwarmed["target_position"].iloc[:-1].eq(0.0).all()
    assert underwarmed["target_position"].iloc[-1] != 0.0
    assert underwarmed["position"].eq(0.0).all()
