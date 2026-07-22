from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gpt_quant import StrategyConfig, run_backtest

_REPORT_DIR = Path(__file__).parents[1] / "reports" / "research" / "extra-execution-delay"
_RESULT_PATH = _REPORT_DIR / "result.json"
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location(
        "extra_execution_delay_analysis",
        _ANALYSIS_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load extra-execution-delay analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_backtest_frame(btc_usdt_prices: pd.Series) -> pd.DataFrame:
    return run_backtest(
        btc_usdt_prices,
        StrategyConfig(
            annualization=365,
            min_position=0.0,
            transaction_cost_bps=10.0,
        ),
    ).frame


def test_extra_delay_reprices_real_execution_from_cash(btc_usdt_prices: pd.Series) -> None:
    module = _load_analysis_module()
    original = _real_backtest_frame(btc_usdt_prices)
    original_copy = original.copy(deep=True)

    delayed = module.apply_extra_execution_delay(original)

    expected_position = original["position"].shift(1).fillna(0.0)
    expected_turnover = expected_position.diff().abs()
    expected_turnover.iloc[0] = abs(expected_position.iloc[0])
    expected_cost = expected_turnover * 0.001
    expected_return = expected_position * original["asset_return"] - expected_cost

    pd.testing.assert_series_equal(delayed["position"], expected_position, check_names=False)
    pd.testing.assert_series_equal(delayed["turnover"], expected_turnover, check_names=False)
    pd.testing.assert_series_equal(delayed["trading_cost"], expected_cost, check_names=False)
    pd.testing.assert_series_equal(delayed["strategy_return"], expected_return, check_names=False)
    assert delayed["position"].iloc[0] == 0.0
    pd.testing.assert_frame_equal(original, original_copy)


def test_delay_bootstrap_is_deterministic_on_real_returns(btc_usdt_prices: pd.Series) -> None:
    module = _load_analysis_module()
    delayed = module.apply_extra_execution_delay(_real_backtest_frame(btc_usdt_prices))
    values = delayed["strategy_return"].to_numpy(dtype=float)

    first = module.analyze_delayed_returns(values, seed=20260722)
    repeated = module.analyze_delayed_returns(values, seed=20260722)

    assert first == repeated
    assert first["observations"] == len(values)
    assert first["bootstrap"]["ci_lower"] <= first["bootstrap"]["ci_upper"]


def test_delay_stress_rejects_invalid_cost_without_computing_returns(
    btc_usdt_prices: pd.Series,
) -> None:
    module = _load_analysis_module()
    frame = _real_backtest_frame(btc_usdt_prices)

    with pytest.raises(ValueError, match="finite and non-negative"):
        module.apply_extra_execution_delay(frame, transaction_cost_bps=np.nan)


def test_extra_execution_delay_report_records_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert result["settings"]["candidate_count"] == 1
    assert result["settings"]["additional_execution_delay_bars"] == 1
    assert result["settings"]["position_source"] == "persisted executed OOS position"
    assert result["settings"]["transaction_cost_bps"] == 10.0
    assert result["settings"]["development_market_screen"] is True
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert result["provenance"]["source_artifact_id"] == 8515639605
    assert result["provenance"]["source_workflow_run_id"] == 29883451981
    assert result["failure_reasons"] == [
        "BTC-USDT delayed-return mean lower confidence bound is not positive",
        "ETH-USDT delayed-return mean lower confidence bound is not positive",
    ]

    expected = {
        "BTC-USDT": {
            "report": "eadade3fd883744d6bf9edeb798a0c8ca2bd62b621d936c70717a4e38e11fd9a",
            "returns": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
            "annualized_mean": 0.15681837632870427,
            "ci_lower": -0.030123464816100204,
            "total_return": 1.2660643660939415,
        },
        "ETH-USDT": {
            "report": "b2bf91d7ed00e016931ffe4d892827d769a44fb0dae8af58bc1d6785a0207067",
            "returns": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
            "annualized_mean": 0.16778888568199307,
            "ci_lower": -0.01481680822337768,
            "total_return": 1.3751779648607303,
        },
    }
    for market, expected_market in expected.items():
        market_result = result["markets"][market]
        assert market_result["report_sha256"] == expected_market["report"]
        assert market_result["returns_sha256"] == expected_market["returns"]
        assert market_result["observations"] == 2340
        assert market_result["annualized_mean"] == pytest.approx(
            expected_market["annualized_mean"], abs=0.0
        )
        assert market_result["bootstrap"]["ci_lower"] == pytest.approx(
            expected_market["ci_lower"], abs=0.0
        )
        assert market_result["total_return"] == pytest.approx(
            expected_market["total_return"], abs=0.0
        )
        assert market_result["bootstrap"]["lower_bound_positive"] is False
