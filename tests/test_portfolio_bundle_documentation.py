from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_README_PATH = _REPOSITORY_ROOT / "README.md"
_REPRODUCTION_PATH = _REPOSITORY_ROOT / "docs" / "REPRODUCTION.md"
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github" / "workflows" / "hourly-research.yml"
_PORTFOLIO_SCRIPT_PATH = _REPOSITORY_ROOT / "scripts" / "run_portfolio_risk.py"
_PORTFOLIO_STRESS_PATH = _REPOSITORY_ROOT / "src" / "gpt_quant" / "portfolio_stress.py"
_BUNDLE_RECOVERY_TEST_PATH = _REPOSITORY_ROOT / "tests" / "test_portfolio_stress_correlation.py"
_INCOMPLETE_ROLLBACK_TEST_PATH = (
    _REPOSITORY_ROOT / "tests" / "test_portfolio_stress_bundle_incomplete_rollback.py"
)

_OUTPUTS = (
    "portfolio_risk.json",
    "portfolio_returns.csv",
    "portfolio_risk.md",
    "portfolio_stress_correlation.json",
)


def test_docs_match_four_file_portfolio_artifact_bundle() -> None:
    readme = _README_PATH.read_text(encoding="utf-8")
    reproduction = _REPRODUCTION_PATH.read_text(encoding="utf-8")
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    script = _PORTFOLIO_SCRIPT_PATH.read_text(encoding="utf-8")
    stress_module = _PORTFOLIO_STRESS_PATH.read_text(encoding="utf-8")
    recovery_test = _BUNDLE_RECOVERY_TEST_PATH.read_text(encoding="utf-8")
    incomplete_rollback_test = _INCOMPLETE_ROLLBACK_TEST_PATH.read_text(encoding="utf-8")

    for output in _OUTPUTS:
        assert output in readme
        assert reproduction.count(output) == 1
        assert output in stress_module
        assert f'"{output}"' in recovery_test
        assert f'"{output}"' in incomplete_rollback_test

    assert "paths = write_portfolio_risk_bundle(result, args.output_dir)" in script
    assert "path: reports/portfolio/" in workflow

    for declaration in (
        '"json": "portfolio_risk.json"',
        '"returns": "portfolio_returns.csv"',
        '"markdown": "portfolio_risk.md"',
        '"stress_correlation": _STRESS_CORRELATION_FILENAME',
    ):
        assert declaration in stress_module

    diagnostic_start = stress_module.index("def build_portfolio_stress_correlation_diagnostic(")
    standalone_start = stress_module.index("def write_portfolio_stress_correlation_report(")
    diagnostic = stress_module[diagnostic_start:standalone_start]
    for claim in (
        "report_only=True",
        'gate_status="not_evaluated"',
        '"threshold": None',
        "development-market diagnostic only; not used for selection or pass/reject",
    ):
        assert claim in diagnostic

    bundle_start = stress_module.index("def write_portfolio_risk_bundle(")
    bundle = stress_module[bundle_start:]
    for claim in (
        "staged_paths = write_portfolio_risk_report(result, staging)",
        'staged_paths["stress_correlation"] = write_portfolio_stress_correlation_report(',
        "for name in _PORTFOLIO_BUNDLE_FILENAMES:",
        "os.replace(staged_paths[name], destinations[name])",
        "for name in reversed(replaced):",
        "portfolio bundle commit failed and rollback was incomplete",
    ):
        assert claim in bundle

    assert bundle.index(
        "staged_paths = write_portfolio_risk_report(result, staging)"
    ) < bundle.index(
        'staged_paths["stress_correlation"] = write_portfolio_stress_correlation_report('
    )
    assert bundle.index("os.replace(staged_paths[name], destinations[name])") < bundle.index(
        "for name in reversed(replaced):"
    )

    assert "if final_replacements == 4" in recovery_test
    assert "for name, path in original_paths.items()" in recovery_test
    assert "portfolio bundle commit failed and rollback was incomplete" in (
        incomplete_rollback_test
    )

    for claim in (
        "同一四文件 generation",
        "`report_only=true`",
        "`gate_status=not_evaluated`",
        "`threshold=null`",
        "不参与聚合风险门禁",
        "lower-level 三文件 core writer",
        "JSON、returns、Markdown、stress correlation 顺序",
        "恢复原有四个文件的精确字节",
        "`portfolio bundle commit failed and rollback was incomplete`",
        "只适用于 staging 层",
    ):
        assert claim in readme

    for claim in (
        "四文件 portfolio bundle",
        "`report_only=true`",
        "`gate_status=not_evaluated`",
        "`threshold=null`",
        "不参与 `concentration.passes`",
        "JSON、returns、Markdown、stress correlation 顺序",
        "`portfolio bundle commit failed and rollback was incomplete`",
        "lower-level 三文件 core writer",
        "不能当作一致的 workflow artifact 证据",
    ):
        assert claim in reproduction
