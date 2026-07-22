from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATHS = (
    _REPOSITORY_ROOT / ".github/workflows/hourly-research.yml",
    _REPOSITORY_ROOT / ".github/workflows/package-build.yml",
)
_SETUP_PYTHON_V7 = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"
_SETUP_PYTHON_V6 = "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1"


def test_ci_workflows_pin_setup_python_v7() -> None:
    for workflow_path in _WORKFLOW_PATHS:
        workflow = workflow_path.read_text(encoding="utf-8")

        assert workflow.count("actions/setup-python@") == 1
        assert workflow.count(_SETUP_PYTHON_V7) == 1
        assert _SETUP_PYTHON_V6 not in workflow
        assert "pip-install:" not in workflow
        assert workflow.count("cache: pip") == 1
