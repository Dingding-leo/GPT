from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, WalkForwardResult, run_walk_forward_research

_CONFIG_PATH = Path("config/okx_research.json")
_EXPECTED_ONE_WAY_COSTS_BPS = [5.0, 7.5, 10.0, 15.0]


def _experiment_config() -> dict[str, Any]:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def _selected_identity(result: WalkForwardResult) -> tuple[int, int, float]:
    assert len(result.folds) == 1
    selected = result.folds[0]["selected_parameters"]
    return (
        int(selected["momentum_lookback"]),
        int(selected["reversal_lookback"]),
        float(selected["trend_weight"]),
    )


def test_declared_fee_baseline_maps_to_absolute_cost_sensitivities() -> None:
    experiment = _experiment_config()
    strategy = experiment["strategy"]
    robustness = experiment["robustness"]

    fee_bps = float(strategy["transaction_cost_bps"])
    multipliers = [float(value) for value in robustness["cost_multipliers"]]
    absolute_costs_bps = [fee_bps * value for value in multipliers]

    assert fee_bps == 5.0
    assert absolute_costs_bps == _EXPECTED_ONE_WAY_COSTS_BPS


def test_canonical_baseline_selects_every_fold_under_five_bps(
    btc_usdt_prices: pd.Series,
) -> None:
    experiment = _experiment_config()
    strategy = experiment["strategy"]
    search = experiment["search"]
    robustness = experiment["robustness"]

    base_config = StrategyConfig(**strategy)
    result = run_walk_forward_research(
        btc_usdt_prices.iloc[:900],
        base_config=base_config,
        momentum_lookbacks=search["momentum_lookbacks"],
        reversal_lookbacks=search["reversal_lookbacks"],
        trend_weights=search["trend_weights"],
        selection_bars=search["selection_bars"],
        test_bars=search["test_bars"],
        cost_multipliers=robustness["cost_multipliers"],
    )

    selected_fold_fees = {
        float(fold["selected_parameters"]["transaction_cost_bps"])
        for fold in result.folds
    }
    multipliers = [float(value) for value in result.settings["cost_multipliers"]]
    absolute_costs_bps = [
        base_config.transaction_cost_bps * value for value in multipliers
    ]
    cost_drag = [
        result.cost_stress_metrics[f"{multiplier:g}x"]["cost_drag_sum"]
        for multiplier in multipliers
    ]

    assert result.settings["candidate_count"] == 27
    assert all(fold["candidates_tested"] == 27 for fold in result.folds)
    assert result.settings["base_config"]["transaction_cost_bps"] == 5.0
    assert selected_fold_fees == {5.0}
    assert result.cost_stress_metrics["1x"] == pytest.approx(result.aggregate_metrics)
    assert multipliers == [1.0, 1.5, 2.0, 3.0]
    assert absolute_costs_bps == _EXPECTED_ONE_WAY_COSTS_BPS
    assert cost_drag == sorted(cost_drag)


def test_five_bps_baseline_reselects_instead_of_repricing_ten_bps_path(
    btc_usdt_prices: pd.Series,
) -> None:
    experiment = _experiment_config()
    strategy = experiment["strategy"]
    search = experiment["search"]
    robustness = experiment["robustness"]

    prices = btc_usdt_prices.iloc[175:565]
    common_arguments = {
        "momentum_lookbacks": search["momentum_lookbacks"],
        "reversal_lookbacks": search["reversal_lookbacks"],
        "trend_weights": search["trend_weights"],
        "selection_bars": 300,
        "test_bars": 90,
        "cost_multipliers": robustness["cost_multipliers"],
    }
    five_bps = run_walk_forward_research(
        prices,
        base_config=StrategyConfig(**strategy),
        **common_arguments,
    )
    ten_bps = run_walk_forward_research(
        prices,
        base_config=StrategyConfig(**strategy).with_overrides(transaction_cost_bps=10.0),
        **common_arguments,
    )

    assert five_bps.folds[0]["candidates_tested"] == 27
    assert ten_bps.folds[0]["candidates_tested"] == 27
    assert _selected_identity(five_bps) == (90, 2, 0.85)
    assert _selected_identity(ten_bps) == (90, 10, 0.85)
    assert _selected_identity(five_bps) != _selected_identity(ten_bps)
