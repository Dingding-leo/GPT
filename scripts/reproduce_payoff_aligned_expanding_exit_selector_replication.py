#!/usr/bin/env python3
"""Run the archived deterministic reproducer for issue #742."""

from __future__ import annotations

import base64
import gzip
from pathlib import Path

ARCHIVE = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "payoff-aligned-expanding-exit-selector-replication-1h-v1"
    / "reproducer.py.gz.b64"
)

source = gzip.decompress(base64.b64decode(ARCHIVE.read_text())).decode()
exec(
    compile(source, "reproduce_payoff_aligned_expanding_exit_selector.py", "exec"),
    {"__name__": "__main__", "__file__": str(ARCHIVE)},
)
