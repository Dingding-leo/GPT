from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "WALK_FORWARD_REPORT_AUDIT.md"
WALK_FORWARD = ROOT / "src" / "gpt_quant" / "walk_forward.py"
REPORT_WRITER = ROOT / "src" / "gpt_quant" / "walk_forward_report.py"


def _documented_audit_code() -> str:
    guide = GUIDE.read_text(encoding="utf-8")
    marked = guide.split("<!-- walk-forward-stability-audit:start -->", maxsplit=1)[1]
    block = marked.split("<!-- walk-forward-stability-audit:end -->", maxsplit=1)[0]
    command = next(line for line in block.splitlines() if line.startswith("python -c "))
    prefix = 'python -c "'
    assert command.startswith(prefix)
    assert command.endswith('"')
    return command[len(prefix) : -1]


def _write_report(root: Path, *, first_count: int) -> None:
    report = {
        "folds": [
            {
                "selected_parameters": {
                    "momentum_lookback": 21,
                    "reversal_lookback": 3,
                    "trend_weight": 0.7,
                }
            },
            {
                "selected_parameters": {
                    "momentum_lookback": 21,
                    "reversal_lookback": 3,
                    "trend_weight": 0.70000000001,
                }
            },
            {
                "selected_parameters": {
                    "momentum_lookback": 21,
                    "reversal_lookback": 3,
                    "trend_weight": 0.7,
                }
            },
        ],
        "parameter_stability": {
            "selection_frequency_records": [
                {
                    "momentum_lookback": 21,
                    "reversal_lookback": 3,
                    "trend_weight": 0.7,
                    "selections": first_count,
                },
                {
                    "momentum_lookback": 21,
                    "reversal_lookback": 3,
                    "trend_weight": 0.70000000001,
                    "selections": 1,
                },
            ],
        },
    }
    path = root / "reports" / "okx" / "BTC-USDT" / "walk_forward.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report), encoding="utf-8")


def test_documented_parameter_stability_audit_detects_count_drift(tmp_path: Path) -> None:
    code = _documented_audit_code()
    _write_report(tmp_path, first_count=2)

    valid = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )
    assert valid.returncode == 0, valid.stderr
    assert valid.stdout.strip() == "parameter_stability=verified"

    _write_report(tmp_path, first_count=1)
    invalid = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        check=False,
        text=True,
    )
    assert invalid.returncode != 0
    assert "AssertionError" in invalid.stderr


def test_parameter_stability_guide_matches_report_write_boundary() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    walk_forward = WALK_FORWARD.read_text(encoding="utf-8")
    report_writer = REPORT_WRITER.read_text(encoding="utf-8")

    for claim in (
        "parameter_stability.selection_frequency_records",
        "parameter_stability.selection_frequency",
        "0.7` 与 `0.70000000001",
        "parameter_stability=verified",
        "创建输出目录和写入任何报告文件之前",
    ):
        assert claim in guide

    assert 'payload["selection_frequency_records"] = _selection_frequency_records(' in walk_forward
    assert "does not match selected fold parameters" in walk_forward
    assert report_writer.index("payload = result.to_dict()") < report_writer.index(
        "output.mkdir(parents=True, exist_ok=True)"
    )
