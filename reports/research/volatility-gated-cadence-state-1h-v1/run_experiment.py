#!/usr/bin/env python3
"""Run the frozen cadence experiment from its immutable preregistered source."""

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


def main() -> None:
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": "gpt-research-replay/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        source = response.read()
    if not source.startswith(b"#!/usr/bin/env python3\n"):
        raise RuntimeError("immutable experiment source is malformed")
    target: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="volatility_gated_cadence_",
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
