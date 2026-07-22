from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import gpt_quant.walk_forward as walk_forward
from gpt_quant import StrategyConfig, run_walk_forward_research

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_okx_research.py"


def _load_runner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_okx_research_control_cli", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_kwargs() -> dict[str, object]:
    return {
        "base_config": StrategyConfig(
            min_position=0.0,
            transaction_cost_bps=10.0,
            annualization=365,
        ),
        "momentum_lookbacks": [21],
        "reversal_lookbacks": [3],
        "trend_weights": [0.7],
        "selection_bars": 300,
        "test_bars": 100,
        "cost_multipliers": [1.0, 2.0],
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("selection_bars", 300.5, "selection_bars must be an integer"),
        ("selection_bars", "300", "selection_bars must be an integer"),
        ("selection_bars", True, "selection_bars must be an integer"),
        ("selection_bars", 99, "selection_bars must be >= 100"),
        ("test_bars", 100.5, "test_bars must be an integer"),
        ("test_bars", "100", "test_bars must be an integer"),
        ("test_bars", False, "test_bars must be an integer"),
        ("test_bars", 19, "test_bars must be >= 20"),
        ("cost_multipliers", [1.0, "2"], "cost multipliers must be finite and positive"),
        ("cost_multipliers", [1.0, True], "cost multipliers must be finite and positive"),
        ("cost_multipliers", [1.0, float("nan")], "cost multipliers must be finite and positive"),
        ("cost_multipliers", [1.0, float("inf")], "cost multipliers must be finite and positive"),
        ("cost_multipliers", [1.0, 0.0], "cost multipliers must be finite and positive"),
        ("cost_multipliers", [1.0, -1.0], "cost multipliers must be finite and positive"),
    ],
)
def test_walk_forward_rejects_coerced_controls_before_backtesting(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    kwargs = _base_kwargs()
    kwargs[field] = value

    def unexpected_backtest(*_args: object, **_kwargs: object) -> None:
        pytest.fail("control validation must run before any backtest")

    monkeypatch.setattr(walk_forward, "run_backtest", unexpected_backtest)
    with pytest.raises(ValueError, match=message):
        run_walk_forward_research(btc_usdt_prices.iloc[:400], **kwargs)


def test_walk_forward_accepts_numpy_control_scalars(btc_usdt_prices: pd.Series) -> None:
    result = run_walk_forward_research(
        btc_usdt_prices.iloc[:400],
        **{
            **_base_kwargs(),
            "selection_bars": np.int64(300),
            "test_bars": np.int32(100),
            "cost_multipliers": [np.float64(1.0), np.float32(2.0)],
        },
    )

    assert result.settings["selection_bars"] == 300
    assert result.settings["test_bars"] == 100
    assert result.settings["cost_multipliers"] == [1.0, 2.0]
    assert type(result.settings["selection_bars"]) is int
    assert type(result.settings["test_bars"]) is int
    assert all(type(value) is float for value in result.settings["cost_multipliers"])


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("search", "selection_bars", 300.5, "selection_bars must be an integer"),
        ("search", "test_bars", "100", "test_bars must be an integer"),
        (
            "robustness",
            "cost_multipliers",
            [1.0, "2"],
            "cost multipliers must be finite and positive",
        ),
    ],
)
def test_okx_runner_preserves_control_types_for_library_validation(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    section: str,
    field: str,
    value: object,
    message: str,
) -> None:
    module = _load_runner()
    experiment: dict[str, object] = {
        "data": {},
        "strategy": {
            "min_position": 0.0,
            "transaction_cost_bps": 10.0,
            "annualization": 365,
        },
        "search": {
            "momentum_lookbacks": [21],
            "reversal_lookbacks": [3],
            "trend_weights": [0.7],
            "selection_bars": 300,
            "test_bars": 100,
        },
        "robustness": {"cost_multipliers": [1.0, 2.0]},
    }
    target = experiment[section]
    assert isinstance(target, dict)
    target[field] = value
    snapshot = SimpleNamespace(close=btc_usdt_prices, raw_pages=(), metadata={})

    def unexpected_backtest(*_args: object, **_kwargs: object) -> None:
        pytest.fail("malformed OKX controls reached backtest execution")

    monkeypatch.setattr(sys, "argv", [str(_SCRIPT_PATH)])
    monkeypatch.setattr(module, "load_json", lambda _path: experiment)
    monkeypatch.setattr(module, "fetch_okx_history_candles", lambda **_kwargs: snapshot)
    monkeypatch.setattr(module, "write_okx_snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(walk_forward, "run_backtest", unexpected_backtest)

    with pytest.raises(ValueError, match=message):
        module.main()


def test_okx_cost_multipliers_must_be_json_array() -> None:
    module = _load_runner()

    with pytest.raises(ValueError, match="cost_multipliers must be a JSON array"):
        module._json_array({"cost_multipliers": "2"}, "cost_multipliers", [1.0, 2.0])
