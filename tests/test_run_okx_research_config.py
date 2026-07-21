from __future__ import annotations

import importlib.util
from types import ModuleType


def _load_run_okx_research_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "run_okx_research_cli", "scripts/run_okx_research.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load scripts/run_okx_research.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_effective_config_records_executed_cost_stresses() -> None:
    module = _load_run_okx_research_module()
    requested_cost_multipliers = [1.0]
    result_settings = {
        "candidate_count": 1,
        "cost_multipliers": [*requested_cost_multipliers, 2.0],
    }

    effective_config = module._build_effective_config(
        data={"inst_id": "BTC-USDT", "bar": "1Dutc"},
        strategy={"transaction_cost_bps": 10.0},
        search={"selection_bars": 730, "test_bars": 90},
        result_settings=result_settings,
    )

    assert requested_cost_multipliers == [1.0]
    assert effective_config["robustness"]["cost_multipliers"] == [1.0, 2.0]
