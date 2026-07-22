from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest, run_holdout_research
from gpt_quant.features import build_target_position


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
    return float(frame["trading_cost"].sum() - frame.at[first, "trading_cost"] + entry_cost)


def _explicit_target_position(prices: pd.Series, config: StrategyConfig) -> pd.Series:
    log_returns = np.log(prices.astype(float)).diff()
    trend_weight, reversal_weight = config.normalized_weights()
    values: list[float] = []

    for offset in range(len(prices)):
        trend_window = log_returns.iloc[
            offset - config.momentum_lookback + 1 : offset + 1
        ].to_numpy(dtype=float)
        reversal_window = log_returns.iloc[
            offset - config.reversal_lookback + 1 : offset + 1
        ].to_numpy(dtype=float)
        volatility_window = log_returns.iloc[
            offset - config.volatility_lookback + 1 : offset + 1
        ].to_numpy(dtype=float)

        if (
            len(trend_window) != config.momentum_lookback
            or len(reversal_window) != config.reversal_lookback
            or len(volatility_window) != config.volatility_lookback
            or not np.isfinite(trend_window).all()
            or not np.isfinite(reversal_window).all()
            or not np.isfinite(volatility_window).all()
        ):
            values.append(0.0)
            continue

        trend_std = float(np.std(trend_window, ddof=0))
        risk_scale = float(np.std(volatility_window, ddof=0))
        if trend_std == 0.0 or risk_scale == 0.0:
            values.append(0.0)
            continue

        trend_score = float(np.mean(trend_window)) / trend_std * math.sqrt(config.momentum_lookback)
        reversal_score = -float(np.sum(reversal_window)) / (
            risk_scale * math.sqrt(config.reversal_lookback)
        )
        ensemble_score = float(
            np.clip(trend_weight * trend_score + reversal_weight * reversal_score, -4.0, 4.0)
        )
        directional_signal = math.tanh(ensemble_score)
        realized_volatility = risk_scale * math.sqrt(config.annualization)
        volatility_scalar = float(
            np.clip(
                config.target_volatility / realized_volatility,
                0.0,
                config.max_abs_position,
            )
        )
        values.append(
            float(
                np.clip(
                    directional_signal * volatility_scalar,
                    config.min_position,
                    config.max_abs_position,
                )
            )
        )

    return pd.Series(values, index=prices.index, name="target_position")


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


def test_extending_sealed_holdout_cannot_change_validation_selection(
    btc_usdt_prices: pd.Series,
) -> None:
    common = {
        "base_config": StrategyConfig(),
        "momentum_lookbacks": [21, 63],
        "reversal_lookbacks": [3, 5],
        "trend_weights": [0.6, 0.8],
        "top_candidates": 8,
    }
    short_holdout = run_holdout_research(
        btc_usdt_prices.iloc[:600],
        validation_fraction=0.1875,
        holdout_fraction=0.0625,
        **common,
    )
    extended_holdout = run_holdout_research(
        btc_usdt_prices.iloc[:900],
        validation_fraction=0.125,
        holdout_fraction=0.375,
        **common,
    )

    for boundary in ("validation_start", "validation_end", "holdout_start"):
        assert short_holdout.split[boundary] == extended_holdout.split[boundary]
    assert short_holdout.split["holdout_end"] != extended_holdout.split["holdout_end"]
    assert short_holdout.holdout_metrics["observations"] == 38
    assert extended_holdout.holdout_metrics["observations"] == 338
    assert short_holdout.holdout_metrics["total_return"] != pytest.approx(
        extended_holdout.holdout_metrics["total_return"]
    )
    assert short_holdout.benchmark_holdout_metrics["total_return"] != pytest.approx(
        extended_holdout.benchmark_holdout_metrics["total_return"]
    )
    assert short_holdout.candidates_tested == extended_holdout.candidates_tested == 8
    assert short_holdout.selected_parameters == extended_holdout.selected_parameters
    assert short_holdout.selection_score == pytest.approx(extended_holdout.selection_score)
    assert short_holdout.validation_metrics == extended_holdout.validation_metrics
    assert short_holdout.candidate_ranking == extended_holdout.candidate_ranking


def test_target_position_matches_explicit_point_in_time_oracle(
    btc_usdt_prices: pd.Series,
) -> None:
    prices = btc_usdt_prices.iloc[:600]
    config = StrategyConfig(
        momentum_lookback=63,
        reversal_lookback=5,
        volatility_lookback=21,
        target_volatility=0.7,
        max_abs_position=0.9,
        min_position=-0.4,
        trend_weight=0.65,
        reversal_weight=0.35,
        annualization=365,
    )

    expected = _explicit_target_position(prices, config)
    actual = build_target_position(prices, config)

    assert actual.ne(0.0).any()
    pd.testing.assert_series_equal(actual, expected, rtol=1e-12, atol=1e-12)


def test_target_position_prefix_cannot_use_later_observations(
    btc_usdt_prices: pd.Series,
) -> None:
    config = StrategyConfig(
        momentum_lookback=63,
        reversal_lookback=5,
        volatility_lookback=21,
    )
    earlier = btc_usdt_prices.iloc[:600]
    extended = btc_usdt_prices.iloc[:900]

    original = build_target_position(earlier, config)
    recalculated = build_target_position(extended, config).loc[original.index]

    pd.testing.assert_series_equal(original, recalculated, check_exact=True)


@pytest.mark.parametrize(
    "config",
    [
        pytest.param(
            StrategyConfig(
                momentum_lookback=63,
                reversal_lookback=5,
                volatility_lookback=21,
                trend_weight=1.0,
                reversal_weight=0.0,
            ),
            id="trend-only",
        ),
        pytest.param(
            StrategyConfig(
                momentum_lookback=63,
                reversal_lookback=5,
                volatility_lookback=21,
                trend_weight=0.0,
                reversal_weight=1.0,
            ),
            id="reversal-only",
        ),
    ],
)
def test_individual_signal_paths_cannot_use_later_observations(
    btc_usdt_prices: pd.Series,
    config: StrategyConfig,
) -> None:
    earlier = btc_usdt_prices.iloc[:600]
    extended = btc_usdt_prices.iloc[:900]

    original = build_target_position(earlier, config)
    recalculated = build_target_position(extended, config).loc[original.index]

    assert original.ne(0.0).any()
    pd.testing.assert_series_equal(original, recalculated, check_exact=True)


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

    assert result.benchmark_holdout_metrics["cost_drag_sum"] == pytest.approx(cost_bps / 10_000.0)
