from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"
_CHECKOUT_V7 = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
_SETUP_PYTHON_V7 = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"
_UPLOAD_ARTIFACT_V7 = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1"


def test_dependency_audit_workflow_pins_ci_infrastructure() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.count("runs-on: ubuntu-24.04") == 1
    assert "runs-on: ubuntu-latest" not in workflow

    assert workflow.count("actions/checkout@") == 1
    assert workflow.count(_CHECKOUT_V7) == 1
    assert workflow.count("persist-credentials: false") == 1

    assert workflow.count("actions/setup-python@") == 1
    assert workflow.count(_SETUP_PYTHON_V7) == 1

    assert workflow.count("actions/upload-artifact@") == 1
    assert workflow.count(_UPLOAD_ARTIFACT_V7) == 1
