from __future__ import annotations

import importlib.util
from pathlib import Path

from gpt_quant.okx_1h import fetch_okx_one_hour_candles as canonical_fetch_okx_one_hour_candles

EXPERIMENT = Path(__file__).with_name("run_cross_venue_spot_coherence.py")

spec = importlib.util.spec_from_file_location("cross_venue_spot_coherence_frozen", EXPERIMENT)
if spec is None or spec.loader is None:
    raise RuntimeError("unable to load frozen cross-venue spot-coherence experiment")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fetch_okx_with_overlap_budget(**kwargs):
    """Allow provider pagination overlap without changing the frozen sample."""

    kwargs["safety_pages"] = 16
    return canonical_fetch_okx_one_hour_candles(**kwargs)


# The initial exact-head run exhausted the generic two-page pagination cushion before
# reaching the frozen 2023-04-01 start. This repair changes only the maximum number of
# public OKX pages the existing strict source reader may consume. The requested start,
# end, 1H cadence, exact 24,144-row identity, feature, labels, fees, gates, and sealed
# OOS boundary remain unchanged and are still checked by the frozen experiment.
module.fetch_okx_one_hour_candles = fetch_okx_with_overlap_budget
module.main()
