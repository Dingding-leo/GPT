from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_walk_forward_research

_CONFIG_PATH = Path("config/okx_research.json")
_EXPECTED_ONE_WAY_COSTS_BPS = [5.0, 7.5, 10.0, 15.0]


def _experiment_config() -> dict[str, object]:
    return json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))


def test_declared_fee_baseline_maps_to_absolute_cost_sensitivities() -> None:
    experiment = _experiment_config()
    strategy = experiment["strategy"]
    robustness = experiment["robustness"]
    assert isinstance(strategy, dict)
    assert isinstance(robustness, dict)

    fee_bps = float(strategy["transaction_cost_bps"])
    multipliers = [float(value) for value in robustness["cost_multipliers"]]

    assert fee_bps == 5.0
    assert [fee_bps * value for value in multipliers] == _EXPECTED_ONE_WAY_COSTS_BPS


def test_canonical_baseline_selects_every_fold_under_five_bps(
    btc_usdt_prices: pd.Series,
) -> None:
    experiment = _experiment_config()
    strategy = experiment["strategy"]
    search = experiment["search"]
    robustness = experiment["robustness"]
    assert isinstance(strategy, dict)
    assert isinstance(search, dict)
    assert isinstance(robustness, dict)

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

    assert result.settings["candidate_count"] == 27
    assert result.settings["base_config"]["transaction_cost_bps"] == 5.0
    assert all(
        fold["selected_parameters"]["transaction_cost_bps"] == 5.0
        for fold in result.folds
    )
    assert result.cost_stress_metrics["1x"] == pytest.approx(result.aggregate_metrics)
    assert result.settings["cost_multipliers"] == [1.0, 1.5, 2.0, 3.0]

    cost_drag = [
        result.cost_stress_metrics[f"{multiplier:g}x"]["cost_drag_sum"]
        for multiplier in result.settings["cost_multipliers"]
    ]
    assert cost_drag == sorted(cost_drag)
    assert [
        base_config.transaction_cost_bps * multiplier
        for multiplier in result.settings["cost_multipliers"]
    ] == _EXPECTED_ONE_WAY_COSTS_BPS
