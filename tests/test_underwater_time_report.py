from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

_REPORT_DIR = Path(__file__).parents[1] / "reports" / "research" / "underwater-time"
_RESULT_PATH = _REPORT_DIR / "result.json"
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location(
        "underwater_time_analysis", _ANALYSIS_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load underwater-time analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_underwater_fraction_matches_independent_real_data_calculation(
    btc_usdt_prices,
) -> None:
    module = _load_analysis_module()
    returns = btc_usdt_prices.pct_change().dropna().to_numpy(dtype=float)

    nav = np.cumprod(1.0 + returns)
    running_peak = np.maximum.accumulate(np.concatenate(([1.0], nav)))[1:]
    expected = float(np.mean(nav < running_peak - 1e-12))

    assert module.underwater_fraction(returns) == pytest.approx(expected, abs=0.0)


def test_underwater_time_report_records_rejected_joint_hypothesis() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 4
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert result["settings"]["development_market_screen"] is True
    assert result["provenance"]["source_artifact_id"] == 8507019983
    assert result["provenance"]["source_workflow_run_id"] == 29860303180
    assert result["metric_screen"]["underwater_fraction"]["disposition"] == "primary"

    expected_hashes = {
        "BTC-USDT": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        "ETH-USDT": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
    }
    for market, expected_hash in expected_hashes.items():
        market_result = result["markets"][market]
        primary = market_result["metrics"]["underwater_fraction"]
        assert market_result["sha256"] == expected_hash
        assert market_result["observations"] == 2340
        assert primary["point"]["reduction"] < 0.0
        assert primary["bootstrap"]["lower_bound_positive"] is False
        assert primary["bootstrap"]["ci_lower"] < 0.0 < primary["bootstrap"]["ci_upper"]
