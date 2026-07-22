from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest

import gpt_quant.walk_forward as walk_forward

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_okx_research.py"


def _load_run_okx_research_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_okx_research_candidate_cli", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load {_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("momentum_lookbacks", 21.5, "momentum lookback candidates must be integers"),
        ("momentum_lookbacks", "21", "momentum lookback candidates must be integers"),
        ("reversal_lookbacks", True, "reversal lookback candidates must be integers"),
        ("trend_weights", "0.7", "trend weight candidates must be finite real numbers"),
        ("trend_weights", True, "trend weight candidates must be finite real numbers"),
    ],
)
def test_okx_cli_preserves_candidate_types_for_library_validation(
    btc_usdt_prices: pd.Series,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    module = _load_run_okx_research_module()
    search: dict[str, object] = {
        "momentum_lookbacks": [21],
        "reversal_lookbacks": [3],
        "trend_weights": [0.7],
        "selection_bars": 730,
        "test_bars": 90,
    }
    search[field] = [value]
    experiment = {
        "data": {},
        "strategy": {
            "min_position": 0.0,
            "transaction_cost_bps": 10.0,
            "annualization": 365,
        },
        "search": search,
        "robustness": {"cost_multipliers": [1.0, 2.0]},
    }
    snapshot = SimpleNamespace(
        close=btc_usdt_prices,
        raw_pages=(),
        metadata={},
    )

    def unexpected_backtest(*_args: object, **_kwargs: object) -> None:
        pytest.fail("malformed candidate config reached backtest execution")

    monkeypatch.setattr(sys, "argv", [str(_SCRIPT_PATH)])
    monkeypatch.setattr(module, "load_json", lambda _path: experiment)
    monkeypatch.setattr(module, "fetch_okx_history_candles", lambda **_kwargs: snapshot)
    monkeypatch.setattr(module, "write_okx_snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(walk_forward, "run_backtest", unexpected_backtest)

    with pytest.raises(ValueError, match=message):
        module.main()


def test_candidate_config_fields_must_be_json_arrays() -> None:
    module = _load_run_okx_research_module()

    with pytest.raises(ValueError, match="momentum_lookbacks must be a JSON array"):
        module._json_array({"momentum_lookbacks": "21"}, "momentum_lookbacks", [21])
