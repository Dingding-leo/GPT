from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_GUIDE_PATH = _REPOSITORY_ROOT / "docs" / "REPRODUCTION.md"
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github" / "workflows" / "hourly-research.yml"


def test_reproduction_guide_pins_the_hourly_workflow_pip_bootstrap() -> None:
    guide = _GUIDE_PATH.read_text(encoding="utf-8")
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    declaration_prefix = 'PIP_BOOTSTRAP_VERSION: "'
    declaration_line = next(
        line.strip() for line in workflow.splitlines() if declaration_prefix in line
    )
    version = declaration_line.split('"')[1]
    documented_install = f'python -m pip install "pip=={version}"'
    workflow_install = 'python -m pip install "pip==${PIP_BOOTSTRAP_VERSION}"'
    project_install = 'python -m pip install -e ".[dev]"'

    install_start = workflow.index("- name: Install project")
    lint_start = workflow.index("- name: Lint and formatting")
    install_block = workflow[install_start:lint_start]

    assert workflow_install in install_block
    assert project_install in install_block
    assert install_block.index(workflow_install) < install_block.index(project_install)

    assert guide.count(documented_install) == 2
    assert guide.count(project_install) == 2
    assert "python -m pip install --upgrade pip" not in guide
    assert "不要改回不固定版本的 pip bootstrap" in guide
    assert "没有仓库 commit" in guide

    macos_start = guide.index("### macOS / Linux")
    windows_start = guide.index("### Windows PowerShell")
    version_recording = guide.index("记录用于复现的代码版本")
    assert documented_install in guide[macos_start:windows_start]
    assert documented_install in guide[windows_start:version_recording]
