from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPOSITORY_ROOT = Path(__file__).parents[1]
_VERIFIER = _REPOSITORY_ROOT / "scripts" / "verify_walk_forward_metrics.py"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_verifier_rejects_nonstandard_json_constants_before_returns_io(
    tmp_path: Path,
    constant: str,
) -> None:
    report_path = tmp_path / "walk_forward.json"
    returns_path = tmp_path / "missing-walk-forward-returns.csv"
    report_path.write_text(f'{{"invalid":{constant}}}\n', encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(_VERIFIER),
            "--report-json",
            str(report_path),
            "--returns-csv",
            str(returns_path),
        ],
        cwd=_REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 1
    assert (
        f"report JSON contains non-standard numeric constant '{constant}'"
        in completed.stderr
    )
    assert not returns_path.exists()
