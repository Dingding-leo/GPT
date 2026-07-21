from __future__ import annotations

import subprocess
import sys


def test_run_research_requires_verified_snapshot_manifest() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/run_research.py"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 2
    assert "--snapshot-manifest" in completed.stderr
    assert "required" in completed.stderr
