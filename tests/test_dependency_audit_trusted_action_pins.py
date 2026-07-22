from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"
_CHECKOUT_V7 = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
_CHECKOUT_V5 = "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"
_SETUP_PYTHON_V7 = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"
_SETUP_PYTHON_V6 = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"


def test_dependency_audit_pins_trusted_actions_without_unsafe_pr_checkout() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.count("actions/checkout@") == 1
    assert workflow.count(_CHECKOUT_V7) == 1
    assert _CHECKOUT_V5 not in workflow
    assert workflow.count("actions/setup-python@") == 1
    assert workflow.count(_SETUP_PYTHON_V7) == 1
    assert _SETUP_PYTHON_V6 not in workflow
    assert "allow-unsafe-pr-checkout:" not in workflow

    checkout_index = workflow.index(_CHECKOUT_V7)
    base_ref_index = workflow.index(
        "ref: ${{ github.event.pull_request.base.sha }}", checkout_index
    )
    credentials_index = workflow.index("persist-credentials: false", base_ref_index)
    setup_python_index = workflow.index(_SETUP_PYTHON_V7, credentials_index)

    assert checkout_index < base_ref_index < credentials_index < setup_python_index
