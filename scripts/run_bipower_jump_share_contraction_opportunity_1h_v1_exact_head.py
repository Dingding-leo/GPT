from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from gpt_quant.okx_1h import fetch_okx_one_hour_candles

MODULE_PATH = Path(__file__).with_name(
    "run_bipower_jump_share_contraction_opportunity_1h_v1.py"
)


def _load_experiment() -> ModuleType:
    spec = importlib.util.spec_from_file_location("bipower_jump_share_experiment", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load frozen bipower jump-share experiment")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fetch_source(module: ModuleType, instrument: str) -> tuple[Any, Any]:
    primary = fetch_okx_one_hour_candles(
        inst_id=instrument,
        start=module.START,
        end=module.END,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=100,
    )
    repeat = fetch_okx_one_hour_candles(
        inst_id=instrument,
        start=module.START,
        end=module.END,
        pause_seconds=0.12,
        timeout=20.0,
        safety_pages=100,
    )
    return primary, repeat


def main() -> None:
    module = _load_experiment()
    module._fetch_source = lambda instrument: _fetch_source(module, instrument)
    module.main()


if __name__ == "__main__":
    main()
