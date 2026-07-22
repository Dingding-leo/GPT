from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/hourly-research.yml"


def test_hourly_portfolio_declares_variance_contribution_budget() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    declaration = 'MAX_VARIANCE_CONTRIBUTION: "0.75"'
    argument = '--max-variance-contribution "$MAX_VARIANCE_CONTRIBUTION"'
    correlation_declaration = 'MAX_PAIRWISE_CORRELATION: "0.90"'
    correlation_argument = '--max-pairwise-correlation "$MAX_PAIRWISE_CORRELATION"'
    fail_closed_argument = "--fail-on-reject"
    rejected_report_upload_guard = (
        "if: ${{ always() && hashFiles('reports/portfolio/portfolio_risk.json') != '' }}"
    )
    portfolio_start = workflow.index("- name: Generate verified portfolio risk report")
    portfolio_upload = workflow.index("- name: Upload verified portfolio risk artifact")
    portfolio_block = workflow[portfolio_start:portfolio_upload]
    upload_block = workflow[portfolio_upload:]

    assert workflow.count(declaration) == 1
    assert workflow.count(argument) == 1
    assert workflow.index(declaration) < portfolio_start
    assert argument in portfolio_block
    assert workflow.count(correlation_declaration) == 1
    assert workflow.count(correlation_argument) == 1
    assert workflow.index(correlation_declaration) < portfolio_start
    assert correlation_argument in portfolio_block
    assert workflow.count(fail_closed_argument) == 1
    assert fail_closed_argument in portfolio_block
    assert workflow.count(rejected_report_upload_guard) == 1
    assert rejected_report_upload_guard in upload_block
