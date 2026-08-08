from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd

BASE_PATH = Path(__file__).with_name("run_perpetual_taker_flow_absorption.py")
spec = importlib.util.spec_from_file_location("perpetual_taker_flow_absorption_base", BASE_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("cannot load frozen perpetual taker-flow absorption implementation")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)


def _canonical_frame_bytes(frame: pd.DataFrame) -> bytes:
    """Match the repository's immutable OKX normalized-CSV identity exactly.

    This is the single permitted pre-result correctness repair for #1105. It
    changes only provenance serialization; no target, source, date, feature,
    sign, window, fee, label, bootstrap, fold, gate, or OOS boundary changes.
    """

    output = frame.reset_index(names="timestamp").to_csv(
        index=False,
        date_format="%Y-%m-%dT%H:%M:%S.%fZ",
        float_format="%.12g",
        lineterminator="\n",
    )
    return output.encode()


base._canonical_frame_bytes = _canonical_frame_bytes
base.main()
