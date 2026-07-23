from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUIDE = ROOT / "docs" / "WALK_FORWARD_REPORT_AUDIT.md"
WALK_FORWARD = ROOT / "src" / "gpt_quant" / "walk_forward.py"
REPORT_WRITER = ROOT / "src" / "gpt_quant" / "walk_forward_report.py"
METRICS = ROOT / "src" / "gpt_quant" / "metrics.py"
RESEARCH = ROOT / "src" / "gpt_quant" / "research.py"
HOLDOUT_CLI = ROOT / "scripts" / "run_research.py"
INSOLVENCY_TEST = ROOT / "tests" / "test_insolvency_validation.py"


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


def test_solvency_guide_matches_metric_and_holdout_report_boundaries() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    metrics = METRICS.read_text(encoding="utf-8")
    research = RESEARCH.read_text(encoding="utf-8")
    holdout_cli = HOLDOUT_CLI.read_text(encoding="utf-8")
    insolvency_test = INSOLVENCY_TEST.read_text(encoding="utf-8")

    for claim in (
        "strategy_return <= -1.0",
        "strategy return must remain greater than -100%; insolvency occurs at",
        "未来才发生的破产不会污染在它之前单独提交",
        "run_holdout_research()` 成功返回后写 `latest.json` 与 `latest.md`",
        "pytest tests/test_insolvency_validation.py",
        "结构性修改只用于 fail-closed 验证，不用于计算或报告绩效",
    ):
        assert claim in guide

    assert "insolvent = returns <= -1.0" in metrics
    assert metrics.index("_validate_solvent_returns(returns)") < metrics.index(
        "total_growth ="
    )
    assert research.index("metrics = performance_metrics(validation_frame") < research.index(
        "score = _selection_score(metrics)"
    )
    assert holdout_cli.index("result = run_holdout_research(") < holdout_cli.index(
        "write_research_report(result"
    )

    for evidence in (
        "btc_usdt_prices",
        "test_metrics_before_future_insolvency_remain_valid",
        "test_performance_metrics_rejects_insolvent_repriced_frame",
    ):
        assert evidence in insolvency_test
