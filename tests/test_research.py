from __future__ import annotations

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest, run_holdout_research
from gpt_quant.research import _run_window_from_cash


def _single_candidate_result(prices: pd.Series, config: StrategyConfig):
    return run_holdout_research(
        prices,
        base_config=config,
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=[0.8],
        validation_fraction=0.2,
        holdout_fraction=0.2,
        top_candidates=1,
    )


def test_research_selects_on_validation_and_reports_holdout(
    btc_usdt_prices: pd.Series,
) -> None:
    result = run_holdout_research(
        btc_usdt_prices,
        base_config=StrategyConfig(),
        momentum_lookbacks=[21, 63],
        reversal_lookbacks=[3, 5],
        trend_weights=[0.6, 0.8],
        validation_fraction=0.2,
        holdout_fraction=0.2,
        top_candidates=3,
    )

    assert result.candidates_tested == 8
    assert len(result.candidate_ranking) == 3
    assert result.split["validation_end"] < result.split["holdout_start"]
    assert result.holdout_metrics["observations"] > 0


def test_window_entry_turnover_is_repriced_from_cash(
    btc_usdt_prices: pd.Series,
) -> None:
    config = StrategyConfig(
        momentum_lookback=21,
        reversal_lookback=3,
        trend_weight=0.8,
        reversal_weight=0.2,
        transaction_cost_bps=10.0,
    )
    full = run_backtest(btc_usdt_prices, config).frame
    stable_nonzero = full.index[
        (full["position"].abs() > 0.0) & full["position"].eq(full["position"].shift(1))
    ]
    assert len(stable_nonzero) > 0
    start = stable_nonzero[0]

    inherited = run_backtest(btc_usdt_prices, config, start=start).frame
    repriced = _run_window_from_cash(btc_usdt_prices, config, start=start).frame
    expected_turnover = abs(float(repriced["position"].iloc[0]))
    expected_cost = expected_turnover * config.transaction_cost_bps / 10_000.0

    assert float(inherited["turnover"].iloc[0]) == pytest.approx(0.0)
    assert float(repriced["turnover"].iloc[0]) == pytest.approx(expected_turnover)
    assert float(repriced["trading_cost"].iloc[0]) == pytest.approx(expected_cost)
    assert float(repriced["strategy_return"].iloc[0]) == pytest.approx(
        float(repriced["position"].iloc[0]) * float(repriced["asset_return"].iloc[0])
        - expected_cost
    )
    assert float(repriced["nav"].iloc[0]) == pytest.approx(
        1.0 + float(repriced["strategy_return"].iloc[0])
    )


def test_holdout_benchmark_uses_same_entry_cost_assumption(
    btc_usdt_prices: pd.Series,
) -> None:
    cost_bps = 10.0
    result = _single_candidate_result(
        btc_usdt_prices,
        StrategyConfig(min_position=0.0, transaction_cost_bps=cost_bps),
    )

    assert result.benchmark_holdout_metrics["cost_drag_sum"] == pytest.approx(
        cost_bps / 10_000.0
    )
