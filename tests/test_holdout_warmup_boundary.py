from __future__ import annotations

import pandas as pd
import pytest

import gpt_quant.research as research
from gpt_quant import StrategyConfig, run_holdout_research


def _base_config(*, volatility_lookback: int = 20) -> StrategyConfig:
    return StrategyConfig(
        volatility_lookback=volatility_lookback,
        min_position=0.0,
        transaction_cost_bps=10.0,
        annualization=365,
    )


@pytest.mark.parametrize(
    ("momentum_lookbacks", "reversal_lookbacks", "base_config"),
    [
        ([360], [3], _base_config()),
        ([21], [360], _base_config()),
        ([21], [3], _base_config(volatility_lookback=360)),
    ],
)
def test_holdout_rejects_lookbacks_without_prevalidation_execution_warmup(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    momentum_lookbacks: list[int],
    reversal_lookbacks: list[int],
    base_config: StrategyConfig,
) -> None:
    def unexpected_backtest(*args: object, **kwargs: object) -> None:
        pytest.fail("warmup validation must finish before any backtest")

    monkeypatch.setattr(research, "run_backtest", unexpected_backtest)

    with pytest.raises(
        ValueError,
        match="fully formed one-bar-delayed position at validation start",
    ):
        run_holdout_research(
            btc_usdt_prices.iloc[:600],
            base_config=base_config,
            momentum_lookbacks=momentum_lookbacks,
            reversal_lookbacks=reversal_lookbacks,
            trend_weights=[0.7],
            validation_fraction=0.20,
            holdout_fraction=0.20,
            top_candidates=1,
        )


@pytest.mark.parametrize("lookback_dimension", ["momentum", "reversal", "volatility"])
def test_holdout_accepts_final_prevalidation_execution_warmup_boundary(
    btc_usdt_prices: pd.Series,
    lookback_dimension: str,
) -> None:
    momentum_lookbacks = [21]
    reversal_lookbacks = [3]
    base_config = _base_config()
    if lookback_dimension == "momentum":
        momentum_lookbacks = [359]
    elif lookback_dimension == "reversal":
        reversal_lookbacks = [359]
    else:
        base_config = _base_config(volatility_lookback=359)

    result = run_holdout_research(
        btc_usdt_prices.iloc[:600],
        base_config=base_config,
        momentum_lookbacks=momentum_lookbacks,
        reversal_lookbacks=reversal_lookbacks,
        trend_weights=[0.7],
        validation_fraction=0.20,
        holdout_fraction=0.20,
        top_candidates=1,
    )

    assert result.split["validation_start"] == btc_usdt_prices.index[360].isoformat()
    assert result.candidates_tested == 1
