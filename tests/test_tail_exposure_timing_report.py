from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from gpt_quant import StrategyConfig, run_backtest

_REPORT_DIR = Path(__file__).parents[1] / "reports" / "research" / "tail-exposure-timing"
_RESULT_PATH = _REPORT_DIR / "result.json"
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location(
        "tail_exposure_timing_analysis",
        _ANALYSIS_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load tail-exposure timing analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_tail_exposure_delta_matches_independent_real_data_calculation(
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
    asset_returns = frame["asset_return"].to_numpy(dtype=float)
    positions = frame["position"].to_numpy(dtype=float)

    threshold = float(np.quantile(asset_returns, 0.10))
    tail = asset_returns <= threshold
    expected_tail_position = float(np.mean(positions[tail]))
    expected_non_tail_position = float(np.mean(positions[~tail]))

    result = module.tail_exposure_metrics(asset_returns, positions)

    assert result["tail_return_threshold"] == pytest.approx(threshold, abs=0.0)
    assert result["tail_observations"] == int(tail.sum())
    assert result["non_tail_observations"] == int((~tail).sum())
    assert result["tail_mean_position"] == pytest.approx(expected_tail_position, abs=0.0)
    assert result["non_tail_mean_position"] == pytest.approx(expected_non_tail_position, abs=0.0)
    assert result["exposure_delta"] == pytest.approx(
        expected_non_tail_position - expected_tail_position,
        abs=0.0,
    )


def test_tail_exposure_report_records_rejected_joint_hypothesis() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert result["settings"]["candidate_count"] == 1
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert result["settings"]["development_market_screen"] is True
    assert result["settings"]["tail_probability"] == pytest.approx(0.10, abs=0.0)
    assert result["provenance"]["source_artifact_id"] == 8512566174
    assert result["provenance"]["source_workflow_run_id"] == 29874768418
    assert result["provenance"]["source_base_commit"] == (
        "60251e9d945be29645aca86d4133e18ae9a90652"
    )

    expected_hashes = {
        "BTC-USDT": {
            "report": "4b326e6b7553ee4914dadaad48c909d93b2cde7a20b053d18e2db77f9241c203",
            "returns": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        },
        "ETH-USDT": {
            "report": "e80e2c2087951dae66771110ba363a5e798da0638e84cf5af1d07736bb31baeb",
            "returns": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        },
    }
    for market, hashes in expected_hashes.items():
        market_result = result["markets"][market]
        assert market_result["report_sha256"] == hashes["report"]
        assert market_result["returns_sha256"] == hashes["returns"]
        assert market_result["observations"] == 2340
        assert market_result["point"]["tail_observations"] == 234
        assert market_result["point"]["non_tail_observations"] == 2106
        assert market_result["point"]["exposure_delta"] > 0.0
        assert market_result["bootstrap"]["lower_bound_positive"] is False
        assert market_result["bootstrap"]["ci_lower"] < 0.0 < market_result["bootstrap"]["ci_upper"]
