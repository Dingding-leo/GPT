from pathlib import Path

_WORKFLOW_PATH = Path(__file__).parents[1] / ".github/workflows/hourly-research.yml"


def test_hourly_workflow_pins_pip_bootstrap_before_project_install() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    version_declaration = 'PIP_BOOTSTRAP_VERSION: "26.1.2"'
    pinned_install = 'python -m pip install "pip==${PIP_BOOTSTRAP_VERSION}"'
    project_install = 'python -m pip install -e ".[dev]"'

    assert version_declaration in workflow
    assert workflow.count(pinned_install) == 1
    assert "pip install --upgrade pip" not in workflow
    assert workflow.index(version_declaration) < workflow.index(pinned_install)
    assert workflow.index(pinned_install) < workflow.index(project_install)
