from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"


def test_dependency_audit_pins_the_hosted_runner_family() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.count("runs-on: ubuntu-24.04") == 1
    assert "runs-on: ubuntu-latest" not in workflow
