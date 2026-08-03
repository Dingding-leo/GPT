from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).with_name("run_return_sign_mixture_eprocess_shift_1h_v1.py")
SPEC = importlib.util.spec_from_file_location("return_sign_mixture_eprocess_v1", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("unable to load the frozen return-sign diagnostic")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
_ORIGINAL_FETCH = MODULE.fetch_okx_one_hour_candles


def _fetch_with_repaired_page_budget(*args: Any, **kwargs: Any) -> Any:
    kwargs["safety_pages"] = max(int(kwargs.get("safety_pages", 0)), 96)
    return _ORIGINAL_FETCH(*args, **kwargs)


MODULE.fetch_okx_one_hour_candles = _fetch_with_repaired_page_budget

if __name__ == "__main__":
    MODULE.main()
