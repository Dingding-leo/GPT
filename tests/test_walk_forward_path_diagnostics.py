from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_walk_forward_research
from gpt_quant.walk_forward_diagnostics import walk_forward_path_diagnostics
from gpt_quant.walk_forward_report import write_walk_forward_report


def _real_okx_result(prices: pd.Series):
    return run_walk_forward_research(
        prices.iloc[:500],
        base_config=StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=5.0,
            annualization=365,
        ),
        momentum_lookbacks=[21],
        reversal_lookbacks=[3],
        trend_weights=[0.7],
        selection_bars=300,
        test_bars=100,
        cost_multipliers=[1.0, 1.5, 2.0, 3.0],
        provenance={
            "provider": "OKX",
            "instrument_id": "BTC-USDT",
            "bar": "1Dutc",
        },
    )


def _assert_diagnostics_equal(
    actual: dict[str, float | int | str],
    expected: dict[str, float | int | str],
) -> None:
    assert actual.keys() == expected.keys()
    for key, expected_value in expected.items():
        actual_value = actual[key]
        if isinstance(expected_value, float):
            assert actual_value == pytest.approx(expected_value, abs=1e-12)
        else:
            assert actual_value == expected_value


def test_report_persists_recomputable_position_path_diagnostics(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    result = _real_okx_result(btc_usdt_prices)
    expected = walk_forward_path_diagnostics(
        result.combined_frame,
        annualization=365,
    )

    paths = write_walk_forward_report(result, tmp_path)
    payload = json.loads(paths["json"].read_text(encoding="utf-8"))
    _assert_diagnostics_equal(payload["path_diagnostics"], expected)

    persisted = pd.read_csv(paths["returns"], parse_dates=["timestamp"]).set_index("timestamp")
    recomputed = walk_forward_path_diagnostics(persisted, annualization=365)
    _assert_diagnostics_equal(recomputed, expected)

    assert expected["observations"] == len(result.combined_frame)
    assert expected["total_absolute_turnover"] == pytest.approx(
        result.combined_frame["turnover"].sum(),
        abs=1e-12,
    )
    assert expected["position_adjustment_count"] == int(
        (result.combined_frame["turnover"] > 1e-12).sum()
    )
    assert expected["current_absolute_exposure"] == pytest.approx(
        abs(result.combined_frame["position"].iloc[-1]),
        abs=1e-12,
    )
    assert expected["completed_holding_episode_count"] + expected[
        "open_holding_episode_count"
    ] == expected["holding_episode_count"]

    markdown = paths["markdown"].read_text(encoding="utf-8")
    assert "## Position-path diagnostics" in markdown
    assert "not exchange orders or fills" in markdown


def test_position_path_diagnostics_reject_turnover_not_derived_from_position(
    btc_usdt_prices: pd.Series,
) -> None:
    result = _real_okx_result(btc_usdt_prices)
    corrupted = result.combined_frame.copy()
    corrupted.iloc[10, corrupted.columns.get_loc("turnover")] += 0.1

    with pytest.raises(ValueError, match="absolute position changes"):
        walk_forward_path_diagnostics(corrupted, annualization=365)
