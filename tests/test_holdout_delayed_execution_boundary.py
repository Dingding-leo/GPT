from __future__ import annotations

import pandas as pd
import pytest

from gpt_quant import StrategyConfig
from gpt_quant.backtest import run_backtest

_VALIDATION_START_INDEX = 360
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
def test_holdout_warmup_boundary_matches_delayed_execution(
    btc_usdt_prices: pd.Series,
    dimension: str,
) -> None:
    prices = btc_usdt_prices.iloc[:600]
    validation_start = prices.index[_VALIDATION_START_INDEX]

    last_executable = run_backtest(
        prices,
        _boundary_config(
            dimension=dimension,
            lookback=_VALIDATION_START_INDEX - 1,
        ),
    ).frame
    underwarmed = run_backtest(
        prices,
        _boundary_config(
            dimension=dimension,
            lookback=_VALIDATION_START_INDEX,
        ),
    ).frame

    # Allow both position signs so a fully formed real-data signal cannot be
    # clipped to cash; this regression checks timing, not strategy performance.
    assert last_executable.loc[:validation_start, "position"].iloc[:-1].eq(0.0).all()
    assert last_executable.at[validation_start, "position"] == pytest.approx(
        last_executable["target_position"].iloc[_VALIDATION_START_INDEX - 1]
    )
    assert last_executable.at[validation_start, "position"] != 0.0

    assert underwarmed.loc[:validation_start, "target_position"].iloc[:-1].eq(0.0).all()
    assert underwarmed.at[validation_start, "target_position"] != 0.0
    assert underwarmed.loc[:validation_start, "position"].eq(0.0).all()
    assert underwarmed["position"].iloc[_VALIDATION_START_INDEX + 1] == pytest.approx(
        underwarmed.at[validation_start, "target_position"]
    )
