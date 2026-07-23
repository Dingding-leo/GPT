import json
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUDIT_INPUT_SCRIPT = REPOSITORY_ROOT / "scripts" / "dependency_audit_inputs.py"


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


def _quoted(requirement: str) -> str:
    return json.dumps(requirement)


def _pyproject(requirement: str, *, location: str) -> str:
    build_requirement = requirement if location == "build" else "setuptools>=69"
    project_requirement = requirement if location == "project" else "numpy>=1.26,<3"
    optional_section = ""
    if location == "optional":
        optional_section = (
            f"\n[project.optional-dependencies]\nplatform-test = [{_quoted(requirement)}]\n"
        )
    return f"""
[build-system]
requires = [{_quoted(build_requirement)}]
build-backend = "setuptools.build_meta"

[project]
name = "platform-marker-policy-test"
version = "1.0.0"
requires-python = ">=3.11,<3.15"
dependencies = [{_quoted(project_requirement)}]
{optional_section}
""".lstrip()


@pytest.mark.parametrize("location", ["build", "project", "optional"])
@pytest.mark.parametrize(
    "requirement",
    [
        "example>=1; sys_platform == 'win32'",
        "example>=1; platform_system == 'Darwin'",
        "example>=1; platform_machine == 'arm64'",
        "example>=1; os_name == 'nt'",
        "example>=1; implementation_name == 'pypy'",
        "example>=1; python_full_version < '3.11.5'",
    ],
)
def test_prepare_rejects_environment_markers_not_covered_by_the_matrix(
    tmp_path: Path,
    location: str,
    requirement: str,
) -> None:
    pyproject_path = tmp_path / f"pyproject-{location}.toml"
    output_dir = tmp_path / f"audit-{location}"
    pyproject_path.write_text(_pyproject(requirement, location=location), encoding="utf-8")

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "may reference only 'python_version'" in completed.stderr
    assert not output_dir.exists()


def test_prepare_accepts_markers_covered_by_every_audited_python_minor(tmp_path: Path) -> None:
    requirement = "numpy>=1.26,<3; python_version >= '3.11' and python_version < '3.15'"
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "audit"
    pyproject_path.write_text(_pyproject(requirement, location="project"), encoding="utf-8")

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((output_dir / "dependency-inputs.json").read_text(encoding="utf-8"))
    assert requirement in manifest["project_requirements"]


@pytest.mark.parametrize(
    "requirement",
    [
        "example>=1; 'win32' == 'win32'",
        "example>=1; python_version == '3.11",
        "example>=1;",
    ],
)
def test_prepare_rejects_ambiguous_or_malformed_environment_markers(
    tmp_path: Path,
    requirement: str,
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "audit"
    pyproject_path.write_text(_pyproject(requirement, location="project"), encoding="utf-8")

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "environment marker" in completed.stderr
    assert not output_dir.exists()
