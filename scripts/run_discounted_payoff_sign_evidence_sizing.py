#!/usr/bin/env python3
"""Run the frozen discounted payoff-sign evidence sizing experiment."""

from __future__ import annotations

import base64
import gzip
import re
from pathlib import Path

ARCHIVE = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "discounted-payoff-sign-evidence-sizing-1h-v1"
    / "reproducer.py.gz.b64"
)
source = gzip.decompress(base64.b64decode(ARCHIVE.read_text())).decode()
pattern = re.compile(
    r"            ts = int\(values\[0\]\)\n"
    r"(?:            .*\n){1,4}"
    r"            previous = rows_by_ts\.get\(ts\)\n"
)
replacement = """            ts = int(values[0])
            if ts % 3_600_000 != 0:
                raise ValueError(f"invalid timestamp for {inst}: {values}")
            stamp = pd.Timestamp(ts, unit="ms", tz="UTC")
            if values[8] != "1":
                if stamp > END:
                    continue
                raise ValueError(
                    f"unconfirmed candle inside fixed window for {inst}: {values}"
                )
            previous = rows_by_ts.get(ts)
"""
source, substitutions = pattern.subn(replacement, source, count=1)
if substitutions != 1:
    raise RuntimeError(f"expected one fixed-window candle-boundary patch, got {substitutions}")
exec(
    compile(source, "run_discounted_payoff_sign_evidence_sizing.py", "exec"),
    {"__name__": "__main__", "__file__": str(ARCHIVE)},
)
