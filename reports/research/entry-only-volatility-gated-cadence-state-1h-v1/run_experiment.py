#!/usr/bin/env python3
"""Run the frozen entry-only cadence experiment from immutable source."""

from __future__ import annotations

import os
import sys
import tempfile
import urllib.request
from pathlib import Path

SOURCE_URL = (
    "https://raw.githubusercontent.com/Dingding-leo/GPT/"
    "70cd3e88d8d656628dbe568a66ded10d188fa619/"
    "reports/research/volatility-gated-cadence-state-1h-v1/run_experiment.py"
)

_PATH_NEEDLE = (
    b'        data_root / instrument / "snapshot" / f"okx-{instrument}-1H.normalized.csv",\n'
)
_PATH_REPLACEMENT = _PATH_NEEDLE + (
    b'        data_root / instrument / "snapshot" / f"okx-{instrument}-1H.csv",\n'
)

_SYMMETRIC_STATE = b"""        if midnight or high_vol:
            current_candidate = int(base[t])
            if high_vol and not midnight:
                update_high_vol[t] = True
        candidate[t] = current_candidate
"""
_ENTRY_ONLY_STATE = b"""        if midnight:
            current_candidate = int(base[t])
        elif high_vol and current_candidate == 0 and base[t] == 1:
            current_candidate = 1
            update_high_vol[t] = True
        candidate[t] = current_candidate
"""

_GATE_NEEDLE = b'''        "turnover_below_B0": c["turnover"] < b0["turnover"],
        "edge_per_turn_at_least_B1": c["edge_per_turn_bps"] >= b1["edge_per_turn_bps"],
'''
_GATE_REPLACEMENT = b'''        "turnover_below_B0": c["turnover"] < b0["turnover"],
        "turnover_no_greater_B1": c["turnover"] <= b1["turnover"],
        "edge_per_turn_at_least_B1": c["edge_per_turn_bps"] >= b1["edge_per_turn_bps"],
'''

_REPLACEMENTS = (
    (
        b"# Volatility-gated cadence state \xe2\x80\x94 terminal result",
        b"# Entry-only volatility-gated cadence state \xe2\x80\x94 terminal result",
    ),
    (
        b'"accept_volatility_gated_cadence_state_family"',
        b'"accept_entry_only_volatility_gated_cadence_state_family"',
    ),
    (
        b'"reject_volatility_gated_cadence_state_family"',
        b'"reject_entry_only_volatility_gated_cadence_state_family"',
    ),
    (
        b'"volatility-gated-cadence-state-1h-v1"',
        b'"entry-only-volatility-gated-cadence-state-1h-v1"',
    ),
    (b'"issue": 764,', b'"issue": 767,'),
)


def replace_once(source: bytes, needle: bytes, replacement: bytes, label: str) -> bytes:
    count = source.count(needle)
    if count != 1:
        raise RuntimeError(f"{label} patch matched {count} times, expected exactly once")
    return source.replace(needle, replacement)


def main() -> None:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "gpt-research-replay/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        source = response.read()
    if not source.startswith(b"#!/usr/bin/env python3\n"):
        raise RuntimeError("immutable experiment source is malformed")

    source = replace_once(source, _PATH_NEEDLE, _PATH_REPLACEMENT, "snapshot path")
    source = replace_once(source, _SYMMETRIC_STATE, _ENTRY_ONLY_STATE, "entry-only state")
    source = replace_once(source, _GATE_NEEDLE, _GATE_REPLACEMENT, "B1 turnover gate")
    for index, (needle, replacement) in enumerate(_REPLACEMENTS):
        source = replace_once(source, needle, replacement, f"identity {index}")

    target: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="entry_only_volatility_gated_cadence_",
            suffix=".py",
            delete=False,
        ) as handle:
            handle.write(source)
            target = handle.name
        os.execv(sys.executable, [sys.executable, target, *sys.argv[1:]])
    finally:
        if target is not None:
            Path(target).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
