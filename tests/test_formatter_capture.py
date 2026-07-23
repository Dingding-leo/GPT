from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def test_capture_exact_ruff_output_for_atomic_portfolio_repair() -> None:
    root = Path(__file__).parents[1]
    paths = [
        root / "src" / "gpt_quant" / "portfolio_stress.py",
        root / "scripts" / "run_portfolio_risk.py",
        root / "tests" / "test_portfolio_stress_correlation.py",
    ]
    subprocess.run(["ruff", "check", "--fix", *map(str, paths)], cwd=root, check=True)
    subprocess.run(["ruff", "format", *map(str, paths)], cwd=root, check=True)
    subprocess.run(["ruff", "check", *map(str, paths)], cwd=root, check=True)

    capture = root / "reports" / "portfolio" / "formatter-capture"
    capture.mkdir(parents=True, exist_ok=True)
    for path in paths:
        shutil.copy2(path, capture / path.name)
