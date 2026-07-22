from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"


def test_dependency_audit_ignores_external_pip_configuration() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    pip_commands = [line.strip() for line in workflow.splitlines() if "-m pip " in line]

    assert "PIP_CONFIG_FILE: /dev/null" in workflow
    assert len(pip_commands) == 5
    assert all("-m pip --isolated install" in command for command in pip_commands)
    assert all("-m pip install" not in command for command in pip_commands)
