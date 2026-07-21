from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from gpt_quant import StrategyConfig, run_backtest

_REPORT_DIR = Path(__file__).parents[1] / "reports" / "research" / "exposure-matched-timing"
_RESULT_PATH = _REPORT_DIR / "result.json"
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location(
        "exposure_matched_timing_analysis",
        _ANALYSIS_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load exposure-matched timing analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_exposure_matched_delta_matches_independent_real_data_calculation(
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
    asset = frame["asset_return"].to_numpy(dtype=float)
    positions = frame["position"].to_numpy(dtype=float)

    exposure = float(np.mean(positions))
    matched = exposure * asset
    matched[0] -= exposure * 10.0 / 10_000.0
    expected_delta = float(np.mean(strategy - matched) * 365)

    result = module.exposure_matched_metrics(strategy, asset, positions, 10.0)

    assert result["average_executed_exposure"] == pytest.approx(exposure, abs=0.0)
    assert result["annualized_mean_matched_return"] == pytest.approx(
        float(np.mean(matched) * 365),
        abs=0.0,
    )
    assert result["annualized_mean_return_delta"] == pytest.approx(expected_delta, abs=0.0)
    assert result["matched_total_return"] == pytest.approx(
        float(np.prod(1.0 + matched) - 1.0),
        abs=0.0,
    )


def test_exposure_matched_report_records_rejected_joint_hypothesis() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert result["settings"]["candidate_count"] == 1
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert result["settings"]["development_market_screen"] is True
    assert result["provenance"]["source_artifact_id"] == 8510950190
    assert result["provenance"]["source_workflow_run_id"] == 29870506091
    assert result["provenance"]["source_base_commit"] == (
        "5a76277db73c156f248d276f8722f18ad18eef57"
    )

    expected_hashes = {
        "BTC-USDT": {
            "report": "78b0f635114bad273054167ed7d552c32e707c019cd28fde04a268a131765a3f",
            "returns": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        },
        "ETH-USDT": {
            "report": "dd2d2d870f302f893a752f8db9b1d5cdfdca41f39e824fa6299d5d95eab04b76",
            "returns": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        },
    }
    for market, hashes in expected_hashes.items():
        market_result = result["markets"][market]
        assert market_result["report_sha256"] == hashes["report"]
        assert market_result["returns_sha256"] == hashes["returns"]
        assert market_result["observations"] == 2340
        assert market_result["bootstrap"]["lower_bound_positive"] is False
        assert market_result["bootstrap"]["ci_lower"] < 0.0 < market_result["bootstrap"]["ci_upper"]

    assert result["markets"]["BTC-USDT"]["point"]["annualized_mean_return_delta"] > 0.0
    assert result["markets"]["ETH-USDT"]["point"]["annualized_mean_return_delta"] < 0.0
