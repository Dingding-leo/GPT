from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_README_PATH = _REPOSITORY_ROOT / "README.md"
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github" / "workflows" / "hourly-research.yml"


def test_readme_matches_hourly_portfolio_artifact_pipeline() -> None:
    readme = _README_PATH.read_text(encoding="utf-8")
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    source_pattern = "quant-research-source-<run-number>-attempt-<run-attempt>"
    portfolio_pattern = "quant-portfolio-risk-<run-number>-attempt-<run-attempt>"
    assert readme.count(source_pattern) == 1
    assert readme.count(portfolio_pattern) == 1

    source_declaration = (
        'SOURCE_ARTIFACT_NAME: "quant-research-source-${{ github.run_number }}-'
        'attempt-${{ github.run_attempt }}"'
    )
    portfolio_declaration = (
        'PORTFOLIO_ARTIFACT_NAME: "quant-portfolio-risk-${{ github.run_number }}-'
        'attempt-${{ github.run_attempt }}"'
    )
    assert source_declaration in workflow
    assert portfolio_declaration in workflow

    for output in (
        "portfolio_risk.json",
        "portfolio_risk.md",
        "portfolio_returns.csv",
    ):
        assert readme.count(output) == 1

    research_step = workflow.index("- name: Run OKX rolling out-of-sample research")
    source_upload = workflow.index("- name: Upload immutable sleeve research source")
    portfolio_step = workflow.index("- name: Generate verified portfolio risk report")
    portfolio_upload = workflow.index("- name: Upload verified portfolio risk artifact")
    assert research_step < source_upload < portfolio_step < portfolio_upload

    assert "path: reports/okx/" in workflow
    assert "path: reports/portfolio/" in workflow
    assert workflow.count("retention-days: 14") == 2
    assert "报告和原始数据快照作为 GitHub Actions artifact 保存 14 天。" not in readme
