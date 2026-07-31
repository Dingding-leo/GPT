#!/usr/bin/env python3
"""Run the frozen reference-uplift experiment from the encoded audited source."""
from __future__ import annotations

import base64
import os
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
encoded = "".join(
    (ROOT / f".payload{i:02d}").read_text(encoding="ascii") for i in range(5)
)
source = zlib.decompress(base64.b85decode(encoded.encode("ascii")))
with tempfile.NamedTemporaryFile(
    prefix="reference_uplift_", suffix=".py", delete=False
) as handle:
    handle.write(source)
    target = handle.name
try:
    os.execv(sys.executable, [sys.executable, target, *sys.argv[1:]])
finally:
    Path(target).unlink(missing_ok=True)
