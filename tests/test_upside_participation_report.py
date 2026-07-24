from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from gpt_quant import StrategyConfig, run_backtest

_REPORT_DIR = Path(__file__).parents[1] / "reports" / "research" / "upside-participation"
_RESULT_PATH = _REPORT_DIR / "result.json"
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location("upside_participation_analysis", _ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load upside-participation analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_participation_capture_matches_independent_real_data_calculation(
    btc_usdt_prices,
) -> None:
    module = _load_analysis_module()
    frame = run_backtest(
        btc_usdt_prices,
        StrategyConfig(
            annualization=365,
            min_position=0.0,
            transaction_cost_bps=10.0,
        ),
    ).frame
    strategy = frame["strategy_return"].to_numpy(dtype=float)
    benchmark = frame["asset_return"].to_numpy(dtype=float)
    upside = benchmark > 0.0
    downside = benchmark < 0.0

    expected_upside = float(np.mean(strategy[upside]) / np.mean(benchmark[upside]))
    expected_downside = float(np.mean(strategy[downside]) / np.mean(benchmark[downside]))
    result = module.participation_capture(strategy, benchmark)

    assert result["upside_capture"] == pytest.approx(expected_upside, abs=0.0)
    assert result["downside_capture"] == pytest.approx(expected_downside, abs=0.0)
    assert result["asymmetry"] == pytest.approx(expected_upside - expected_downside, abs=0.0)
    assert result["upside_observations"] == int(np.sum(upside))
    assert result["downside_observations"] == int(np.sum(downside))


def test_upside_participation_report_records_rejected_joint_hypothesis() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert result["settings"]["development_market_screen"] is True
    assert result["provenance"]["source_artifact_id"] == 8509324116
    assert result["provenance"]["source_workflow_run_id"] == 29866245582

    expected_hashes = {
        "BTC-USDT": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "ETH-USDT": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
    }
    for market, expected_hash in expected_hashes.items():
        market_result = result["markets"][market]
        assert market_result["sha256"] == expected_hash
        assert market_result["observations"] == 2340
        assert market_result["point"]["zero_benchmark_observations"] == 0
        assert market_result["bootstrap"]["lower_bound_positive"] is False
        assert market_result["bootstrap"]["ci_lower"] < 0.0 < market_result["bootstrap"]["ci_upper"]
