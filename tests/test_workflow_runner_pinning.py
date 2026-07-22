from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATHS = (
    _REPOSITORY_ROOT / ".github/workflows/hourly-research.yml",
    _REPOSITORY_ROOT / ".github/workflows/package-build.yml",
)


def test_ci_workflows_pin_ubuntu_runner_image() -> None:
    for workflow_path in _WORKFLOW_PATHS:
        workflow = workflow_path.read_text(encoding="utf-8")

        assert workflow.count("runs-on: ubuntu-24.04") == 1
        assert "runs-on: ubuntu-latest" not in workflow
