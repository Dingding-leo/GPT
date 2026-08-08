from __future__ import annotations

import importlib.util
from pathlib import Path

EXACT_PATH = Path(__file__).with_name("run_negative_e2160_margin_recovery_exact.py")
spec = importlib.util.spec_from_file_location("margin_recovery_exact", EXACT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("unable to load exact frozen margin-recovery runner")
exact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exact)

core = exact.core
_original_protocol = core._protocol


def _repaired_fetch(inst_id: str, end: str) -> object:
    """Increase only deterministic pagination headroom after pre-label exhaustion.

    The first exact-head run exhausted its derived page budget before reaching the
    frozen start boundary on the first source arm. Increasing safety pages changes
    no requested timestamp, market, feature, label, fee, fold, bootstrap or gate.
    """

    return core.fetch_okx_one_hour_candles(
        inst_id=inst_id,
        start=core.START,
        end=end,
        limit=100,
        pause_seconds=0.10,
        timeout=20.0,
        safety_pages=12,
    )


def _repaired_protocol() -> dict[str, object]:
    protocol = dict(_original_protocol())
    protocol["source_acquisition_repair"] = {
        "reason": "first pre-label run exhausted deterministic page budget before requested start",
        "original_safety_pages": 2,
        "repaired_safety_pages": 12,
        "requested_interval_changed": False,
        "target_changed": False,
        "feature_or_label_changed": False,
        "fee_or_gate_changed": False,
        "oos_accessed_before_repair": False,
        "target_returns_accessed_before_repair": False,
    }
    return protocol


core._fetch = _repaired_fetch
core._protocol = _repaired_protocol

if __name__ == "__main__":
    exact.main()
