from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATHS = (
    _REPOSITORY_ROOT / ".github/workflows/hourly-research.yml",
    _REPOSITORY_ROOT / ".github/workflows/package-build.yml",
)
_CHECKOUT_V7 = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
_CHECKOUT_V5 = "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"


def test_ci_workflows_pin_checkout_v7_without_unsafe_pr_checkout() -> None:
    for workflow_path in _WORKFLOW_PATHS:
        workflow = workflow_path.read_text(encoding="utf-8")

        assert workflow.count("actions/checkout@") == 1
        assert workflow.count(_CHECKOUT_V7) == 1
        assert _CHECKOUT_V5 not in workflow
        assert "allow-unsafe-pr-checkout:" not in workflow

        checkout_index = workflow.index(_CHECKOUT_V7)
        credentials_index = workflow.index("persist-credentials: false", checkout_index)
        setup_python_index = workflow.index("actions/setup-python@", credentials_index)
        assert checkout_index < credentials_index < setup_python_index
