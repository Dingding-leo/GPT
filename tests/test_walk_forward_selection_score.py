from __future__ import annotations

import pandas as pd
import pytest

import gpt_quant.walk_forward as walk_forward_module
from gpt_quant import StrategyConfig, run_backtest, run_walk_forward_research
from gpt_quant.metrics import performance_metrics


def _run(prices: pd.Series):
    return run_walk_forward_research(
        prices,
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=365,
        ),
        momentum_lookbacks=[30, 90],
        reversal_lookbacks=[2, 5],
        trend_weights=[0.55, 0.70],
        selection_bars=365,
        test_bars=90,
        cost_multipliers=[1.0, 1.5, 2.0, 3.0],
        provenance={"provider": "OKX", "instrument_id": "BTC-USDT"},
    )


def _result_payload(result) -> dict[str, object]:
    payload = result.to_dict()
    payload.pop("generated_at_utc")
    return payload


def _legacy_selection_score(frame: pd.DataFrame, *, annualization: int) -> float:
    return walk_forward_module._score(
        performance_metrics(frame, annualization=annualization)
    )


def test_selection_score_fast_path_preserves_real_okx_walk_forward(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prices = btc_usdt_prices.iloc[:1_100]
    optimized = _run(prices)

    monkeypatch.setattr(
        walk_forward_module,
        "_selection_score",
        _legacy_selection_score,
    )
    baseline = _run(prices)

    assert _result_payload(optimized) == _result_payload(baseline)
    pd.testing.assert_frame_equal(optimized.combined_frame, baseline.combined_frame)
    assert optimized.benchmark_frames.keys() == baseline.benchmark_frames.keys()
    for name in optimized.benchmark_frames:
        pd.testing.assert_frame_equal(
            optimized.benchmark_frames[name],
            baseline.benchmark_frames[name],
        )
    assert optimized.perturbation_frames.keys() == baseline.perturbation_frames.keys()
    for name in optimized.perturbation_frames:
        pd.testing.assert_frame_equal(
            optimized.perturbation_frames[name],
            baseline.perturbation_frames[name],
        )


def test_selection_score_matches_full_metrics_and_rejects_corrupted_accounting(
    btc_usdt_prices: pd.Series,
) -> None:
    config = StrategyConfig(
        momentum_lookback=90,
        reversal_lookback=5,
        min_position=0.0,
        transaction_cost_bps=5.0,
        annualization=365,
    )
    frame = run_backtest(btc_usdt_prices.iloc[:730], config).frame

    assert walk_forward_module._selection_score(
        frame,
        annualization=config.annualization,
    ) == walk_forward_module._score(
        performance_metrics(frame, annualization=config.annualization)
    )

    corrupted = frame.copy()
    corrupted.loc[corrupted.index[-1], "gross_strategy_return"] += 0.01
    with pytest.raises(
        ValueError,
        match="gross_strategy_return must equal position multiplied by asset_return",
    ):
        walk_forward_module._selection_score(
            corrupted,
            annualization=config.annualization,
        )
