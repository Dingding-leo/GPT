import json
import subprocess
import sys
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GUIDE_PATH = REPOSITORY_ROOT / "docs/DEPENDENCY_AUDIT.md"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"
AUDIT_INPUT_SCRIPT = REPOSITORY_ROOT / "scripts/dependency_audit_inputs.py"


def _run_prepare(pyproject_path: Path, output_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(AUDIT_INPUT_SCRIPT),
            "prepare",
            str(pyproject_path),
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_dependency_audit_guide_matches_trusted_workflow_and_policy() -> None:
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    validator = AUDIT_INPUT_SCRIPT.read_text(encoding="utf-8")
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))

    assert "pull_request_target" in guide
    assert "PR head 的 `pyproject.toml`" in guide
    assert "不检出、不安装、也不执行 PR 中的 Python 源码" in guide
    assert "Python `3.11`、`3.12`、`3.13`、`3.14`" in guide
    assert "Linux x86-64、Linux arm64、Windows x86-64" in guide
    assert "macOS x86-64、macOS arm64" in guide
    assert "`--only-binary=:all:`" in guide
    assert "`--dry-run`" in guide
    assert "14 天 artifact" in guide

    checkout = workflow.index("- name: Check out trusted base policy")
    download = workflow.index("- name: Download proposed dependency manifest as data")
    validate = workflow.index("- name: Validate proposed dependency declarations")
    first_install = workflow.index(".resolver-venv/bin/python -m pip install --quiet")
    assert checkout < download < validate < first_install
    assert "ref: ${{ github.event.pull_request.base.sha }}" in workflow
    assert "ref: ${{ github.event.pull_request.head.sha }}" not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "--only-binary=:all:" in workflow
    assert "--dry-run" in workflow
    assert "retention-days: 14" in workflow

    assert pyproject["build-system"]["build-backend"] == "setuptools.build_meta"
    assert pyproject["project"]["requires-python"] == ">=3.11,<3.15"
    assert pyproject["build-system"]["requires"] == ["setuptools>=69"]
    assert pyproject["project"]["dependencies"] == [
        "numpy>=1.26,<3",
        "pandas>=2.1,<3",
    ]
    assert pyproject["project"]["optional-dependencies"]["dev"] == [
        "pytest>=8,<10",
        "ruff>=0.9,<1",
    ]

    for error in (
        "[build-system].backend-path is not allowed",
        "dynamic project metadata is not allowed",
        "[tool.setuptools.dynamic] is not allowed",
        "[tool.setuptools.cmdclass] is not allowed",
    ):
        assert error in validator

    for claim in (
        "`[build-system].backend-path`",
        "`[project].dynamic`",
        "`[tool.setuptools.dynamic]`",
        "`[tool.setuptools.cmdclass]`",
    ):
        assert claim in guide

    assert "setup.py" in guide
    assert "setup.cfg" in guide
    assert "scripts/dependency_audit_inputs.py prepare" in guide
    assert "tests/test_dependency_audit_documentation.py" in guide
    assert "不会在本地复现 GitHub Actions 的全部 20 个 Python/平台解析任务" in guide


def test_documented_prepare_command_emits_current_static_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "dependency-inputs"

    completed = _run_prepare(PYPROJECT_PATH, output_dir)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    manifest = json.loads((output_dir / "dependency-inputs.json").read_text(encoding="utf-8"))
    assert manifest["requires_python"] == ">=3.11,<3.15"
    assert manifest["build_backend"] == "setuptools.build_meta"
    assert manifest["build_requirements"] == ["setuptools>=69"]
    assert manifest["project_requirements"] == [
        "numpy>=1.26,<3",
        "pandas>=2.1,<3",
        "pytest>=8,<10",
        "ruff>=0.9,<1",
    ]
    assert manifest["optional_extras"] == ["dev"]
    assert len(manifest["source_sha256"]) == 64


def test_documented_cmdclass_rejection_fails_before_dependency_outputs(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "dependency-inputs"
    pyproject_path.write_text(
        PYPROJECT_PATH.read_text(encoding="utf-8")
        + '\n[tool.setuptools.cmdclass]\nbuild_py = "package.commands.CustomBuildPy"\n',
        encoding="utf-8",
    )

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "[tool.setuptools.cmdclass] is not allowed" in completed.stderr
    assert not output_dir.exists()
