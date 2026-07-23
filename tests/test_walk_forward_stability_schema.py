from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_walk_forward_research
from gpt_quant.walk_forward import _selection_frequency_records
from gpt_quant.walk_forward_diagnostics import walk_forward_path_diagnostics
from gpt_quant.walk_forward_report import write_walk_forward_report


def test_structured_frequency_preserves_exact_selected_weights() -> None:
    folds = [
        {
            "selected_parameters": {
                "momentum_lookback": 21,
                "reversal_lookback": 3,
                "trend_weight": 0.7,
            }
        },
        {
            "selected_parameters": {
                "momentum_lookback": 21,
                "reversal_lookback": 3,
                "trend_weight": 0.70000000001,
            }
        },
        {
            "selected_parameters": {
                "momentum_lookback": 21,
                "reversal_lookback": 3,
                "trend_weight": 0.7,
            }
        },
    ]

    assert _selection_frequency_records(folds) == [
        {
            "momentum_lookback": 21,
            "reversal_lookback": 3,
            "trend_weight": 0.7,
            "selections": 2,
        },
        {
            "momentum_lookback": 21,
            "reversal_lookback": 3,
            "trend_weight": 0.70000000001,
            "selections": 1,
        },
    ]


@pytest.mark.parametrize(
    ("fold", "message"),
    [
        (None, "must be a mapping"),
        ({"selected_parameters": None}, "must contain selected_parameters"),
        (
            {
                "selected_parameters": {
                    "momentum_lookback": "21",
                    "reversal_lookback": 3,
                    "trend_weight": 0.7,
                }
            },
            "momentum_lookback must be an integer",
        ),
        (
            {
                "selected_parameters": {
                    "momentum_lookback": 21,
                    "reversal_lookback": True,
                    "trend_weight": 0.7,
                }
            },
            "reversal_lookback must be an integer",
        ),
        (
            {
                "selected_parameters": {
                    "momentum_lookback": 21,
                    "reversal_lookback": 3,
                    "trend_weight": "0.7",
                }
            },
            "trend_weight must be a finite real number",
        ),
    ],
)
def test_structured_frequency_rejects_malformed_fold_identity(
    fold: object,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        _selection_frequency_records([fold])


def _real_walk_forward_result(btc_usdt_prices: pd.Series):
    return run_walk_forward_research(
        btc_usdt_prices.iloc[:400],
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=10.0,
            annualization=365,
        ),
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=[0.7, 0.70000000001],
        selection_bars=300,
        test_bars=100,
        cost_multipliers=[1.0, 2.0],
    )


def test_programmatic_and_persisted_payloads_share_structured_identity(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    result = _real_walk_forward_result(btc_usdt_prices)
    legacy_frequency = dict(result.parameter_stability["selection_frequency"])

    programmatic = result.to_dict()
    programmatic["path_diagnostics"] = walk_forward_path_diagnostics(
        result.combined_frame,
        annualization=365,
    )
    paths = write_walk_forward_report(result, tmp_path)
    persisted = json.loads(paths["json"].read_text(encoding="utf-8"))
    stability = persisted["parameter_stability"]

    assert persisted == programmatic
    assert stability["selection_frequency"] == legacy_frequency
    assert "selection_frequency_records" not in result.parameter_stability
    assert stability["selection_frequency_records"] == _selection_frequency_records(result.folds)
    assert sum(item["selections"] for item in stability["selection_frequency_records"]) == len(
        result.folds
    )


def test_programmatic_payload_is_isolated_from_result_state(
    btc_usdt_prices: pd.Series,
) -> None:
    result = _real_walk_forward_result(btc_usdt_prices)
    payload = result.to_dict()

    payload["folds"][0]["selected_parameters"]["trend_weight"] = 0.1
    payload["parameter_stability"]["selection_frequency_records"][0]["selections"] = 999

    refreshed = result.to_dict()
    assert refreshed["folds"][0]["selected_parameters"]["trend_weight"] != 0.1
    assert refreshed["parameter_stability"]["selection_frequency_records"][0]["selections"] != 999


@pytest.mark.parametrize(
    "key",
    [
        "selection_frequency",
        "parameter_switches",
        "parameter_switch_rate",
        "unique_parameter_sets",
    ],
)
def test_programmatic_and_report_payloads_reject_inconsistent_stability(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
    key: str,
) -> None:
    result = _real_walk_forward_result(btc_usdt_prices)
    value = result.parameter_stability[key]
    if isinstance(value, dict):
        result.parameter_stability[key] = {"tampered": len(result.folds)}
    elif isinstance(value, int):
        result.parameter_stability[key] = value + 1
    else:
        result.parameter_stability[key] = float(value) + 0.25

    with pytest.raises(ValueError, match=rf"parameter_stability {key}"):
        result.to_dict()

    output_dir = tmp_path / "report"
    with pytest.raises(ValueError, match=rf"parameter_stability {key}"):
        write_walk_forward_report(result, output_dir)

    assert not output_dir.exists()
