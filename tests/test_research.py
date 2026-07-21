from __future__ import annotations

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest, run_holdout_research


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


def _expected_cost_drag_from_cash(frame: pd.DataFrame, cost_bps: float) -> float:
    first = frame.index[0]
    entry_cost = abs(float(frame.at[first, "position"])) * cost_bps / 10_000.0
    return float(
        frame["trading_cost"].sum() - frame.at[first, "trading_cost"] + entry_cost
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


def test_holdout_research_reprices_window_entry_from_cash(
    btc_usdt_prices: pd.Series,
) -> None:
    base = StrategyConfig(transaction_cost_bps=10.0)
    selected = base.with_overrides(
        momentum_lookback=21,
        reversal_lookback=3,
        trend_weight=0.8,
        reversal_weight=0.2,
    )
    result = _single_candidate_result(btc_usdt_prices, base)

    validation = run_backtest(
        btc_usdt_prices,
        selected,
        start=pd.Timestamp(result.split["validation_start"]),
        end=pd.Timestamp(result.split["validation_end"]),
    ).frame
    holdout = run_backtest(
        btc_usdt_prices,
        selected,
        start=pd.Timestamp(result.split["holdout_start"]),
    ).frame

    assert abs(float(validation["position"].iloc[0])) > 0.0
    assert abs(float(holdout["position"].iloc[0])) > 0.0
    assert float(validation["turnover"].iloc[0]) != pytest.approx(
        abs(float(validation["position"].iloc[0]))
    )
    assert float(holdout["turnover"].iloc[0]) != pytest.approx(
        abs(float(holdout["position"].iloc[0]))
    )
    assert result.validation_metrics["cost_drag_sum"] == pytest.approx(
        _expected_cost_drag_from_cash(validation, selected.transaction_cost_bps)
    )
    assert result.holdout_metrics["cost_drag_sum"] == pytest.approx(
        _expected_cost_drag_from_cash(holdout, selected.transaction_cost_bps)
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
