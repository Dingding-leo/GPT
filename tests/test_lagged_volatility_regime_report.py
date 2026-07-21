from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from gpt_quant import StrategyConfig, run_backtest

_REPORT_DIR = Path(__file__).parents[1] / "reports" / "research" / "lagged-volatility-regimes"
_RESULT_PATH = _REPORT_DIR / "result.json"
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location(
        "lagged_volatility_regime_analysis",
        _ANALYSIS_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load lagged-volatility regime analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_lagged_volatility_excludes_current_real_return(btc_usdt_prices) -> None:
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

    observed = module.lagged_realized_volatility(asset_returns, lookback=20)
    expected_at_boundary = float(np.std(asset_returns[:20], ddof=1))
    assert observed[20] == pytest.approx(expected_at_boundary, abs=0.0)

    rejection_only_copy = asset_returns.copy()
    rejection_only_copy[20] += 0.10
    changed = module.lagged_realized_volatility(rejection_only_copy, lookback=20)
    assert changed[20] == pytest.approx(observed[20], abs=0.0)
    assert changed[21] != pytest.approx(observed[21], abs=0.0)


def test_regime_means_match_independent_real_data_calculation(btc_usdt_prices) -> None:
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
    strategy_returns = frame["strategy_return"].to_numpy(dtype=float)
    prior_volatility = module.lagged_realized_volatility(asset_returns, lookback=20)
    eligible = np.isfinite(prior_volatility)
    prior_volatility = prior_volatility[eligible]
    strategy_returns = strategy_returns[eligible]

    threshold = float(np.median(prior_volatility))
    low = prior_volatility <= threshold
    high = prior_volatility > threshold
    result = module.regime_return_metrics(prior_volatility, strategy_returns)

    assert result["prior_volatility_median"] == pytest.approx(threshold, abs=0.0)
    assert result["low_vol_observations"] == int(low.sum())
    assert result["high_vol_observations"] == int(high.sum())
    assert result["low_vol_annualized_mean"] == pytest.approx(
        float(np.mean(strategy_returns[low]) * 365),
        abs=0.0,
    )
    assert result["high_vol_annualized_mean"] == pytest.approx(
        float(np.mean(strategy_returns[high]) * 365),
        abs=0.0,
    )


def test_lagged_volatility_regime_report_records_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert result["settings"]["candidate_count"] == 1
    assert result["settings"]["volatility_lookback"] == 20
    assert result["settings"]["development_market_screen"] is True
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert result["provenance"]["source_artifact_id"] == 8513672060
    assert result["provenance"]["source_workflow_run_id"] == 29877892427
    assert result["provenance"]["source_base_commit"] == (
        "a2f1ab460409113057198ebdd00e3ce4f6c7bf82"
    )
    assert result["failure_reasons"] == [
        "BTC-USDT low-vol lower confidence bound is not positive",
        "ETH-USDT low-vol lower confidence bound is not positive",
        "ETH-USDT high-vol lower confidence bound is not positive",
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
        assert market_result["eligible_observations"] == 2320
        assert market_result["point"]["low_vol_observations"] == 1160
        assert market_result["point"]["high_vol_observations"] == 1160
        assert market_result["point"]["low_vol_annualized_mean"] > 0.0
        assert market_result["point"]["high_vol_annualized_mean"] > 0.0

    assert result["markets"]["BTC-USDT"]["bootstrap"]["high_vol"][
        "lower_bound_positive"
    ] is True
    assert result["markets"]["BTC-USDT"]["bootstrap"]["low_vol"][
        "lower_bound_positive"
    ] is False
    assert result["markets"]["ETH-USDT"]["bootstrap"]["high_vol"][
        "lower_bound_positive"
    ] is False
    assert result["markets"]["ETH-USDT"]["bootstrap"]["low_vol"][
        "lower_bound_positive"
    ] is False
