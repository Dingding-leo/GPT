from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest

from gpt_quant import StrategyConfig, run_backtest

_REPORT_DIR = Path(__file__).parents[1] / "reports" / "research" / "best-day-dependence"
_RESULT_PATH = _REPORT_DIR / "result.json"
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location(
        "best_day_dependence_analysis",
        _ANALYSIS_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load best-day dependence analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _real_strategy_returns(btc_usdt_prices) -> np.ndarray:
    frame = run_backtest(
        btc_usdt_prices,
        StrategyConfig(
            annualization=365,
            min_position=0.0,
            transaction_cost_bps=10.0,
        ),
    ).frame
    return frame["strategy_return"].to_numpy(dtype=float)


def test_best_day_stress_removes_exact_largest_real_returns(btc_usdt_prices) -> None:
    module = _load_analysis_module()
    strategy_returns = _real_strategy_returns(btc_usdt_prices)
    unchanged = strategy_returns.copy()

    result = module.best_day_stress_metrics(strategy_returns, best_return_fraction=0.01)

    removed = math.ceil(len(strategy_returns) * 0.01)
    ordered = np.sort(strategy_returns, kind="stable")
    retained = ordered[:-removed]
    expected_removed = ordered[-removed:]

    assert np.array_equal(strategy_returns, unchanged)
    assert result["removed_observations"] == removed
    assert result["retained_observations"] == len(strategy_returns) - removed
    assert result["smallest_removed_return"] == pytest.approx(expected_removed[0], abs=0.0)
    assert result["largest_removed_return"] == pytest.approx(expected_removed[-1], abs=0.0)
    assert result["annualized_mean_before_stress"] == pytest.approx(
        float(np.mean(strategy_returns) * 365),
        abs=0.0,
    )
    assert result["annualized_mean_after_stress"] == pytest.approx(
        float(np.mean(retained) * 365),
        abs=0.0,
    )
    assert result["annualized_mean_after_stress"] < result["annualized_mean_before_stress"]


@pytest.mark.parametrize("invalid_fraction", [float("nan"), float("inf"), 0.0, 1.0, -0.01])
def test_best_day_stress_rejects_invalid_fraction(
    btc_usdt_prices,
    invalid_fraction: float,
) -> None:
    module = _load_analysis_module()
    strategy_returns = _real_strategy_returns(btc_usdt_prices)

    with pytest.raises(ValueError, match="best_return_fraction"):
        module.best_day_stress_metrics(
            strategy_returns,
            best_return_fraction=invalid_fraction,
        )


def test_best_day_dependence_report_records_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert result["settings"]["candidate_count"] == 1
    assert result["settings"]["best_return_fraction"] == pytest.approx(0.01, abs=0.0)
    assert result["settings"]["removal_count_rule"] == ("ceil(observations * best_return_fraction)")
    assert result["settings"]["development_market_screen"] is True
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert result["provenance"]["source_artifact_id"] == 8513672060
    assert result["provenance"]["source_workflow_run_id"] == 29877892427
    assert result["failure_reasons"] == [
        "BTC-USDT stressed-mean lower confidence bound is not positive",
        "ETH-USDT stressed-mean lower confidence bound is not positive",
    ]

    expected_hashes = {
        "BTC-USDT": {
            "report": "c5262c4c8c0945b43907f006ca5bf986229c350e5e908d8baa4837cc2de32921",
            "returns": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
        },
        "ETH-USDT": {
            "report": "383d8273cdb12d8b3bfe271b4044eaa664c06018f7f6174f7a52f1ac1fdcdf24",
            "returns": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
        },
    }
    for market, hashes in expected_hashes.items():
        market_result = result["markets"][market]
        assert market_result["report_sha256"] == hashes["report"]
        assert market_result["returns_sha256"] == hashes["returns"]
        assert market_result["observations"] == 2340
        assert market_result["point"]["removed_observations"] == 24
        assert market_result["point"]["retained_observations"] == 2316
        assert market_result["point"]["annualized_mean_before_stress"] > 0.0
        assert market_result["point"]["annualized_mean_after_stress"] < 0.0
        assert market_result["bootstrap"]["lower_bound_positive"] is False
