from __future__ import annotations

import importlib.util
from pathlib import Path

CORE_PATH = Path(__file__).with_name("run_dual_ema_distributed_memory_trend.py")
spec = importlib.util.spec_from_file_location("dual_ema_core", CORE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("unable to load frozen dual-EMA strategy runner")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)

SOURCE_SAFETY_PAGES = 64
_original_protocol = core._protocol


def _repaired_fetch(inst_id: str, *, end: str) -> object:
    """Increase deterministic pagination headroom only.

    The first frozen execution exhausted the derived page budget on LTC-USDT
    before reaching the unchanged requested start. This repair changes no
    provider, instrument, timeframe, date boundary, market observation, EMA
    span, signal, fee, benchmark, sample split, bootstrap draw, or gate.
    """

    return core.fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=core.START,
        end=end,
        limit=100,
        pause_seconds=0.10,
        timeout=20.0,
        safety_pages=SOURCE_SAFETY_PAGES,
    )


def _repaired_protocol() -> dict[str, object]:
    protocol = dict(_original_protocol())
    protocol["source_acquisition_repair"] = {
        "reason": "first frozen run exhausted deterministic page budget before requested start",
        "original_safety_pages": 12,
        "repaired_safety_pages": SOURCE_SAFETY_PAGES,
        "requested_interval_changed": False,
        "target_changed": False,
        "strategy_or_benchmark_changed": False,
        "fee_or_gate_changed": False,
        "performance_accessed_before_repair": False,
        "oos_accessed_before_repair": False,
    }
    return protocol


core._fetch = _repaired_fetch
core._protocol = _repaired_protocol

if __name__ == "__main__":
    core.main()
