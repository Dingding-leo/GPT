#!/usr/bin/env python3
"""Run the frozen discounted payoff-sign evidence sizing experiment."""

from __future__ import annotations

import base64
import gzip
from pathlib import Path

ARCHIVE = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "discounted-payoff-sign-evidence-sizing-1h-v1"
    / "reproducer.py.gz.b64"
)
source = gzip.decompress(base64.b64decode(ARCHIVE.read_text())).decode()
exec(
    compile(source, "run_discounted_payoff_sign_evidence_sizing.py", "exec"),
    {"__name__": "__main__", "__file__": str(ARCHIVE)},
)
