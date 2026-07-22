from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from gpt_quant import StrategyConfig, run_backtest

_REPORT_DIR = (
    Path(__file__).parents[1] / "reports" / "research" / "chronological-half-consistency"
)
_RESULT_PATH = _REPORT_DIR / "result.json"
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"


def _load_analysis_module():
    spec = importlib.util.spec_from_file_location(
        "chronological_half_consistency_analysis",
        _ANALYSIS_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load chronological-half analysis module")
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


def _even_real_returns(btc_usdt_prices) -> np.ndarray:
    values = _real_strategy_returns(btc_usdt_prices)
    even_length = len(values) - len(values) % 2
    return values[:even_length]


def test_chronological_halves_preserve_real_order_and_isolate_future(btc_usdt_prices) -> None:
    module = _load_analysis_module()
    values = _even_real_returns(btc_usdt_prices)
    original = values.copy()

    first, second = module.chronological_halves(values)

    assert len(first) == len(second) == len(values) // 2
    assert np.array_equal(np.concatenate([first, second]), original)
    second[0] = second[0] + 0.001
    assert np.array_equal(first, original[: len(first)])
    assert np.array_equal(values, original)


def test_chronological_halves_reject_odd_real_subset(btc_usdt_prices) -> None:
    module = _load_analysis_module()
    values = _real_strategy_returns(btc_usdt_prices)
    odd_values = values if len(values) % 2 else values[:-1]

    with pytest.raises(ValueError, match="even observation count"):
        module.chronological_halves(odd_values)


def test_half_bootstrap_is_deterministic_on_real_returns(btc_usdt_prices) -> None:
    module = _load_analysis_module()
    first, _ = module.chronological_halves(_even_real_returns(btc_usdt_prices))

    first_result = module.analyze_half(first, seed=20260722)
    repeated_result = module.analyze_half(first, seed=20260722)

    assert first_result == repeated_result
    assert first_result["observations"] == len(first)
    assert first_result["bootstrap"]["ci_lower"] <= first_result["bootstrap"]["ci_upper"]


def test_chronological_half_report_records_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert result["settings"]["candidate_count"] == 1
    assert result["settings"]["split_rule"] == "equal chronological halves by observation count"
    assert result["settings"]["development_market_screen"] is True
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert result["provenance"]["source_artifact_id"] == 8513672060
    assert result["provenance"]["source_workflow_run_id"] == 29877892427
    assert result["failure_reasons"] == [
        "BTC-USDT first half mean lower confidence bound is not positive",
        "BTC-USDT second half mean lower confidence bound is not positive",
        "ETH-USDT first half mean lower confidence bound is not positive",
        "ETH-USDT second half mean lower confidence bound is not positive",
    ]

    expected = {
        "BTC-USDT": {
            "report": "c5262c4c8c0945b43907f006ca5bf986229c350e5e908d8baa4837cc2de32921",
            "returns": "539a8a770ae10c702acac250e59daf417e478896284265ee20225de3e676cf73",
            "means": (0.19644480421334354, 0.14693432743659776),
        },
        "ETH-USDT": {
            "report": "383d8273cdb12d8b3bfe271b4044eaa664c06018f7f6174f7a52f1ac1fdcdf24",
            "returns": "027e02ad4c133955b359ba5642fda28ea2e9ad6020895d1eec82d5ec92a379e6",
            "means": (0.22217982617814075, 0.051902079750878724),
        },
    }
    for market, expected_market in expected.items():
        market_result = result["markets"][market]
        assert market_result["report_sha256"] == expected_market["report"]
        assert market_result["returns_sha256"] == expected_market["returns"]
        assert market_result["full_observations"] == 2340
        assert market_result["split_index"] == 1170
        halves = market_result["halves"]
        assert halves["first_half"]["observations"] == 1170
        assert halves["second_half"]["observations"] == 1170
        assert halves["first_half"]["annualized_mean"] == pytest.approx(
            expected_market["means"][0], abs=0.0
        )
        assert halves["second_half"]["annualized_mean"] == pytest.approx(
            expected_market["means"][1], abs=0.0
        )
        assert halves["first_half"]["bootstrap"]["lower_bound_positive"] is False
        assert halves["second_half"]["bootstrap"]["lower_bound_positive"] is False
