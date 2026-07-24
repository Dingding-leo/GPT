from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).parents[1]
_ANALYSIS_PATH = _ROOT / "reports" / "research" / "channel-breakout-trend-1h" / "analysis.py"
_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT" / "okx-BTC-USDT-1H.csv"


def _load_analysis():
    sys.path.insert(0, str(_ANALYSIS_PATH.parent))
    try:
        spec = importlib.util.spec_from_file_location(
            "channel_breakout_analysis",
            _ANALYSIS_PATH,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop("architecture", None)
        sys.path.pop(0)


def _load_fixture(analysis) -> pd.DataFrame:
    frame = pd.read_csv(_FIXTURE_PATH)
    frame.index = analysis.hourly_index(frame.pop("timestamp"))
    return frame


def test_real_okx_channel_target_is_causal_and_bounded() -> None:
    analysis = _load_analysis()
    candles = _load_fixture(analysis)
    original = analysis.target_path(candles, channel=2, regime=2, volatility=2)
    altered = candles.copy()
    altered.iloc[-1, altered.columns.get_loc("high")] *= 1.20
    altered.iloc[-1, altered.columns.get_loc("low")] *= 0.80
    altered.iloc[-1, altered.columns.get_loc("close")] *= 1.10
    changed = analysis.target_path(altered, channel=2, regime=2, volatility=2)

    pd.testing.assert_series_equal(original.iloc[:-1], changed.iloc[:-1])
    assert original.between(0.0, 1.0).all()
    assert changed.between(0.0, 1.0).all()


def test_exact_five_bps_accounting_starts_from_cash() -> None:
    analysis = _load_analysis()
    candles = _load_fixture(analysis)
    target = pd.Series([0.5, 0.25, 0.0], index=candles.index)
    frame = analysis.return_frame(candles, target, candles.index)

    assert frame["position"].iloc[0] == 0.0
    np.testing.assert_allclose(frame["trading_cost"], frame["turnover"] * 0.0005)
    np.testing.assert_allclose(
        frame["strategy_return"],
        frame["gross_strategy_return"] - frame["trading_cost"],
    )


def test_persisted_result_records_single_rejected_candidate() -> None:
    result = json.loads(
        (_ROOT / "reports" / "research" / "channel-breakout-trend-1h" / "result.json").read_text()
    )
    accounting = result["candidate_accounting"]
    assert accounting["architecture_candidates_searched"] == 1
    assert accounting["architecture_candidates_passed"] == 0
    assert accounting["architecture_candidates_rejected"] == 1
    assert result["verdict"] == "rejected"
    assert result["paper_testable"] is False
    assert result["live_eligible"] is False
    assert result["fixed_architecture"]["transaction_cost_bps_one_way"] == 5.0
    assert result["fixed_architecture"]["modeled_cost_paths"] == ["5bps_one_way_only"]
