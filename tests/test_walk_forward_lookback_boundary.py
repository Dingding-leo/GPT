from __future__ import annotations

import pandas as pd
import pytest

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig, WalkForwardResult, run_walk_forward_research

_SELECTION_BARS = 300
_TEST_BARS = 100
_LOOKBACK_DIMENSIONS = ("momentum", "reversal", "volatility")


def _run_boundary_candidate(
    prices: pd.Series,
    *,
    dimension: str,
    lookback: int,
) -> WalkForwardResult:
    base_config = StrategyConfig(
        min_position=0.0,
        transaction_cost_bps=10.0,
        annualization=365,
    )
    momentum_lookbacks = [21]
    reversal_lookbacks = [5]
    if dimension == "momentum":
        momentum_lookbacks = [lookback]
    elif dimension == "reversal":
        reversal_lookbacks = [lookback]
    elif dimension == "volatility":
        base_config = base_config.with_overrides(volatility_lookback=lookback)
    else:
        raise AssertionError(f"unsupported lookback dimension: {dimension}")

    return run_walk_forward_research(
        prices.iloc[: _SELECTION_BARS + _TEST_BARS],
        base_config=base_config,
        momentum_lookbacks=momentum_lookbacks,
        reversal_lookbacks=reversal_lookbacks,
        trend_weights=[0.7],
        selection_bars=_SELECTION_BARS,
        test_bars=_TEST_BARS,
        cost_multipliers=[1.0, 2.0],
    )


@pytest.mark.parametrize("dimension", _LOOKBACK_DIMENSIONS)
def test_walk_forward_rejects_lookback_without_delayed_selection_observation(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    dimension: str,
) -> None:
    def unexpected_backtest(*_args: object, **_kwargs: object) -> None:
        pytest.fail("warmup validation must run before any candidate backtest")

    monkeypatch.setattr(walk_forward, "run_backtest", unexpected_backtest)

    with pytest.raises(
        ValueError,
        match="at least one one-bar-delayed selection-window observation",
    ):
        _run_boundary_candidate(
            btc_usdt_prices,
            dimension=dimension,
            lookback=_SELECTION_BARS - 1,
        )


@pytest.mark.parametrize(
    ("dimension", "lookback"),
    (("momentum", 248), ("reversal", 248), ("volatility", _SELECTION_BARS - 2)),
)
def test_walk_forward_accepts_last_executable_lookback_boundary(
    btc_usdt_prices: pd.Series,
    dimension: str,
    lookback: int,
) -> None:
    result = _run_boundary_candidate(
        btc_usdt_prices,
        dimension=dimension,
        lookback=lookback,
    )

    assert len(result.folds) == 1
    assert result.folds[0]["candidates_tested"] == 1


@pytest.mark.parametrize("dimension", ("momentum", "reversal"))
@pytest.mark.parametrize("lookback", (250, 251))
def test_walk_forward_rejects_underwarmed_longer_lookback_perturbation(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    dimension: str,
    lookback: int,
) -> None:
    def unexpected_backtest(*_args: object, **_kwargs: object) -> None:
        pytest.fail("perturbation warmup validation must run before cache population")

    monkeypatch.setattr(walk_forward, "run_backtest", unexpected_backtest)

    with pytest.raises(
        ValueError,
        match="longer-lookback perturbation",
    ):
        _run_boundary_candidate(
            btc_usdt_prices,
            dimension=dimension,
            lookback=lookback,
        )
