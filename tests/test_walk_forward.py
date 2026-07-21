from __future__ import annotations

import pandas as pd

from gpt_quant import StrategyConfig, run_walk_forward_research
from gpt_quant.walk_forward import _assess_fold_stability, _classify_robustness


def _run(prices: pd.Series):
    return run_walk_forward_research(
        prices,
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=252,
        ),
        momentum_lookbacks=[21, 63],
        reversal_lookbacks=[3],
        trend_weights=[0.6, 0.8],
        selection_bars=300,
        test_bars=100,
        cost_multipliers=[1.0, 2.0, 4.0],
    )


def test_walk_forward_folds_are_non_overlapping_and_charge_boundary_turnover(
    btc_usdt_prices: pd.Series,
) -> None:
    result = _run(btc_usdt_prices.iloc[:700])

    assert len(result.folds) == 4
    assert not result.combined_frame.index.duplicated().any()
    assert result.combined_frame["position"].min() >= 0.0
    assert all(fold["selection_end"] < fold["test_start"] for fold in result.folds)
    assert result.fold_stability["fold_count"] == len(result.folds)

    previous_position = 0.0
    for fold_number in range(1, len(result.folds) + 1):
        frame = result.combined_frame.loc[result.combined_frame["fold"] == fold_number]
        expected = abs(float(frame["position"].iloc[0]) - previous_position)
        assert frame["turnover"].iloc[0] == expected
        previous_position = float(frame["position"].iloc[-1])

    assert (
        result.cost_stress_metrics["4x"]["total_return"]
        <= result.cost_stress_metrics["1x"]["total_return"]
    )


def test_future_observations_cannot_rewrite_prior_walk_forward_results(
    btc_usdt_prices: pd.Series,
) -> None:
    original = _run(btc_usdt_prices.iloc[:700])
    extended = _run(btc_usdt_prices.iloc[:800])
    cutoff = original.combined_frame.index[-1]
    columns = ["position", "turnover", "trading_cost", "strategy_return", "fold"]

    pd.testing.assert_frame_equal(
        original.combined_frame.loc[:cutoff, columns],
        extended.combined_frame.loc[:cutoff, columns],
    )


def _folds(*returns: float) -> list[dict[str, object]]:
    return [{"test_metrics": {"total_return": value}} for value in returns]


def test_fold_stability_rejects_profit_concentrated_in_one_fold() -> None:
    assessment = _assess_fold_stability(_folds(0.30, 0.02, 0.01, -0.01))

    assert assessment["profitable_folds"] == 3
    assert assessment["max_positive_fold_share"] > 0.50
    assert assessment["passes"] is False
    assert "one fold contributes more than half" in assessment["failure_reasons"][0]


def test_fold_stability_accepts_broad_positive_evidence() -> None:
    assessment = _assess_fold_stability(_folds(0.12, 0.11, 0.10, -0.01))

    assert assessment["positive_fold_ratio"] == 0.75
    assert assessment["max_positive_fold_share"] < 0.50
    assert assessment["passes"] is True
    assert assessment["failure_reasons"] == []


def test_provisional_classification_requires_fold_stability() -> None:
    status = _classify_robustness(
        aggregate={"total_return": 0.20, "sharpe": 1.1},
        doubled_cost={"total_return": 0.10},
        perturbation_metrics={
            "a": {"total_return": 0.10},
            "b": {"total_return": 0.08},
            "c": {"total_return": 0.06},
            "d": {"total_return": 0.04},
        },
        benchmark_assessment={
            "beats_all_benchmarks": {
                "total_return": True,
                "sharpe": True,
                "calmar": True,
                "max_drawdown": True,
            }
        },
        fold_stability={"passes": False},
    )

    assert status == "reject: out-of-sample fold profits are too concentrated"
