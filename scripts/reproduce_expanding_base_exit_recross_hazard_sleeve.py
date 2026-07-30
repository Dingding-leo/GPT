#!/usr/bin/env python3
"""Run the archived deterministic reproducer for issue #740."""

from __future__ import annotations

import base64
import gzip
from pathlib import Path

ARCHIVE = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "expanding-base-exit-recross-hazard-sleeve-1h-v1"
    / "reproducer.py.gz.b64"
)

source = gzip.decompress(base64.b64decode(ARCHIVE.read_text())).decode()
exec(
    compile(source, "reproduce_expanding_base_exit_recross_hazard_sleeve.py", "exec"),
    {"__name__": "__main__", "__file__": str(ARCHIVE)},
)
