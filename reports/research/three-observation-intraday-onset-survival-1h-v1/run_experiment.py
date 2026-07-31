#!/usr/bin/env python3
"""Run the frozen three-observation onset-survival experiment."""

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

_INIT_NEEDLE = b"""    current_b1 = 0
    current_candidate = 0
    update_daily = np.zeros(n, dtype=bool)
    update_high_vol = np.zeros(n, dtype=bool)
"""
_INIT_REPLACEMENT = b"""    current_b1 = 0
    current_candidate = 0
    armed = False
    positive_run = 0
    update_daily = np.zeros(n, dtype=bool)
    update_survival = np.zeros(n, dtype=bool)
"""

_LOOP_HEAD_NEEDLE = b"""        midnight = ts.iloc[t].hour == 0
        high_vol = ratio[t] > 1.0
"""
_LOOP_HEAD_REPLACEMENT = b"""        midnight = ts.iloc[t].hour == 0
"""

_SYMMETRIC_STATE = b"""        if midnight or high_vol:
            current_candidate = int(base[t])
            if high_vol and not midnight:
                update_high_vol[t] = True
        candidate[t] = current_candidate
"""
_SURVIVAL_STATE = b"""        if midnight:
            current_candidate = int(base[t])
            armed = False
            positive_run = 0
        elif current_candidate == 0:
            if base[t] == 1:
                if armed:
                    positive_run += 1
                else:
                    armed = True
                    positive_run = 1
                if positive_run >= 3:
                    current_candidate = 1
                    update_survival[t] = True
                    armed = False
                    positive_run = 0
            else:
                armed = False
                positive_run = 0
        candidate[t] = current_candidate
"""

_FEATURE_NEEDLE = b'        "high_vol_update": update_high_vol,\n'
_FEATURE_REPLACEMENT = b'        "survival_update": update_survival,\n'

_EVAL_NEEDLE = b"""    ratio = paths["features"]["ratio"]
    base = paths["features"]["base"]
    high_update = paths["features"]["high_vol_update"]
    daily_update = paths["features"]["daily_update"]
"""
_EVAL_REPLACEMENT = b"""    base = paths["features"]["base"]
    survival_update = paths["features"]["survival_update"]
    daily_update = paths["features"]["daily_update"]
"""

_DIAGNOSTIC_NEEDLE = b"""            "oos_high_vol_ratio_occupancy": float(np.mean(ratio[os:oe] > 1.0)),
            "oos_daily_refresh_decisions": int(np.sum(daily_update[os:oe])),
            "oos_non_midnight_high_vol_refresh_decisions": int(np.sum(high_update[os:oe])),
"""
_DIAGNOSTIC_REPLACEMENT = b"""            "oos_daily_refresh_decisions": int(np.sum(daily_update[os:oe])),
            "oos_non_midnight_survival_entries": int(np.sum(survival_update[os:oe])),
"""

_REPORT_NEEDLE = b"""            f"High-volatility occupancy: {item['diagnostics']['oos_high_vol_ratio_occupancy']:.2%}; non-midnight high-vol refreshes: {item['diagnostics']['oos_non_midnight_high_vol_refresh_decisions']}.",
"""
_REPORT_REPLACEMENT = b"""            f"Non-midnight three-observation survival entries: {item['diagnostics']['oos_non_midnight_survival_entries']}.",
"""

_GATE_NEEDLE = b"""        "turnover_below_B0": c["turnover"] < b0["turnover"],
        "edge_per_turn_at_least_B1": c["edge_per_turn_bps"] >= b1["edge_per_turn_bps"],
"""
_GATE_REPLACEMENT = b"""        "turnover_below_B0": c["turnover"] < b0["turnover"],
        "turnover_no_greater_B1": c["turnover"] <= b1["turnover"],
        "edge_per_turn_at_least_B1": c["edge_per_turn_bps"] >= b1["edge_per_turn_bps"],
"""

_REPLACEMENTS = (
    (
        b"# Volatility-gated cadence state \xe2\x80\x94 terminal result",
        b"# Three-observation intraday onset survival \xe2\x80\x94 terminal result",
    ),
    (
        b'"accept_volatility_gated_cadence_state_family"',
        b'"accept_three_observation_intraday_onset_survival_family"',
    ),
    (
        b'"reject_volatility_gated_cadence_state_family"',
        b'"reject_three_observation_intraday_onset_survival_family"',
    ),
    (
        b'"volatility-gated-cadence-state-1h-v1"',
        b'"three-observation-intraday-onset-survival-1h-v1"',
    ),
    (b'"issue": 764,', b'"issue": 770,'),
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

    patches = (
        (_PATH_NEEDLE, _PATH_REPLACEMENT, "snapshot path"),
        (_INIT_NEEDLE, _INIT_REPLACEMENT, "survival initialization"),
        (_LOOP_HEAD_NEEDLE, _LOOP_HEAD_REPLACEMENT, "loop head"),
        (_SYMMETRIC_STATE, _SURVIVAL_STATE, "survival state"),
        (_FEATURE_NEEDLE, _FEATURE_REPLACEMENT, "survival feature"),
        (_EVAL_NEEDLE, _EVAL_REPLACEMENT, "survival evaluation"),
        (_DIAGNOSTIC_NEEDLE, _DIAGNOSTIC_REPLACEMENT, "survival diagnostics"),
        (_REPORT_NEEDLE, _REPORT_REPLACEMENT, "survival report"),
        (_GATE_NEEDLE, _GATE_REPLACEMENT, "B1 turnover gate"),
    )
    for needle, replacement, label in patches:
        source = replace_once(source, needle, replacement, label)
    for index, (needle, replacement) in enumerate(_REPLACEMENTS):
        source = replace_once(source, needle, replacement, f"identity {index}")

    target: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="three_observation_intraday_onset_survival_",
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
