from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/hourly-research.yml"


def test_hourly_portfolio_declares_variance_contribution_budget() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    declaration = 'MAX_VARIANCE_CONTRIBUTION: "0.75"'
    argument = '--max-variance-contribution "$MAX_VARIANCE_CONTRIBUTION"'
    portfolio_start = workflow.index("- name: Generate verified portfolio risk report")
    portfolio_upload = workflow.index("- name: Upload verified portfolio risk artifact")
    portfolio_block = workflow[portfolio_start:portfolio_upload]

    assert workflow.count(declaration) == 1
    assert workflow.count(argument) == 1
    assert workflow.index(declaration) < portfolio_start
    assert argument in portfolio_block
