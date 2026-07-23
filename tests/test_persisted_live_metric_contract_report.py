from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest

_ANALYSIS_PATH = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "persisted-live-metric-contract"
    / "analysis.py"
)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")
_SPEC = importlib.util.spec_from_file_location("persisted_live_path_metrics", _ANALYSIS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_ANALYSIS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ANALYSIS)


def _real_okx_frame(btc_usdt_prices: pd.Series) -> pd.DataFrame:
    result = run_backtest(
        btc_usdt_prices,
        StrategyConfig(
            momentum_lookback=90,
            reversal_lookback=5,
            volatility_lookback=30,
            target_volatility=0.5,
            min_position=0.0,
            max_abs_position=1.0,
            trend_weight=0.7,
            reversal_weight=0.3,
            transaction_cost_bps=5.0,
            annualization=365,
        ),
    )
    frame = result.frame.reset_index()
    if "timestamp" not in frame:
        frame = frame.rename(columns={frame.columns[0]: "timestamp"})
    frame["fold"] = 1
    return frame


def test_path_diagnostics_reconstruct_from_real_okx_returns(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    source = _real_okx_frame(btc_usdt_prices)
    path = tmp_path / "returns.csv"
    source.to_csv(path, index=False)

    frame = _ANALYSIS._validated_frame(path)
    episodes = _ANALYSIS._episode_metrics(frame)
    months = _ANALYSIS._calendar(frame, "M")
    years = _ANALYSIS._calendar(frame, "Y")
    drawdown = _ANALYSIS._drawdown(frame["strategy_return"])

    assert len(frame) == len(source)
    assert np.isclose(frame["turnover"].sum(), source["turnover"].sum())
    assert episodes["holding_episode_count"] >= episodes["completed_holding_episode_count"]
    assert episodes["open_holding_episode_count"] in {0, 1}
    assert episodes["episode_return_includes_exit_fee"] is True
    assert months[0]["partial"] is True
    assert years[0]["partial"] is True
    assert years[-1]["partial"] is True
    assert drawdown["maximum_drawdown"] <= drawdown["current_drawdown"] <= 0.0
    assert drawdown["longest_underwater_duration_bars"] >= (
        drawdown["current_underwater_duration_bars"]
    )


def test_episode_profit_factor_zero_loss_behavior_is_declared() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
    definition = result["definitions"]["profit_factor"]
    assert "null when there are no losing completed episodes" in definition
    for market in _ANALYSIS.MARKETS:
        metrics = result["markets"][market]["path_metrics"]
        assert metrics["profit_factor_status"] == "finite"
        assert metrics["completed_holding_episode_profit_factor"] > 1.0


def test_committed_result_records_supported_subgate_and_live_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
    assert result["canonical_signature"] == _ANALYSIS.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 1, "rejected": 0}
    assert result["hypothesis_passes"] is True
    assert result["verdict"] == "supported"
    assert result["live_eligible"] is False
    assert result["live_gate_status"]["path_derived_metric_reconstructability"] == "pass"
    assert result["live_gate_status"]["formal_persisted_metric_contract"] == "fail"
    assert result["live_gate_status"]["benchmark_relative_risk_adjusted"] == "fail"
    assert result["live_gate_status"]["fold_stability"] == "fail"
    assert result["live_gate_status"]["year_stability"] == "fail"
    for market in _ANALYSIS.MARKETS:
        market_result = result["markets"][market]
        assert market_result["all_required_path_metrics_reconstructable"] is True
        assert market_result["aggregate_metrics_reconciled"] is True
        assert market_result["missing_path_metrics"] == []
        assert market_result["headline_5bps_metrics"]["fold_count"] == 27
        assert market_result["path_metrics"]["observations"] == 2385
        assert len(market_result["year_records"]) == 7


def test_validator_rejects_position_turnover_mismatch(
    btc_usdt_prices: pd.Series,
    tmp_path: Path,
) -> None:
    frame = _real_okx_frame(btc_usdt_prices)
    frame.loc[frame.index[10], "turnover"] += 0.01
    path = tmp_path / "invalid.csv"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="turnover does not match"):
        _ANALYSIS._validated_frame(path)
