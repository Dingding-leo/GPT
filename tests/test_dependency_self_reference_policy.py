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


def _pyproject(
    *,
    project_name: str = "GPT_Quant.Lab",
    requirement: str = "numpy>=1.26,<3",
    location: str = "project",
) -> str:
    build_requirements = ["setuptools>=69"]
    project_requirements = ["numpy>=1.26,<3"]
    optional_section = ""
    if location == "build":
        build_requirements.append(requirement)
    elif location == "project":
        project_requirements = [requirement]
    elif location == "optional":
        optional_section = (
            f"\n[project.optional-dependencies]\nsecurity-test = [{json.dumps(requirement)}]\n"
        )
    else:
        raise ValueError(f"unsupported test location: {location}")

    return f"""
[build-system]
requires = {json.dumps(build_requirements)}
build-backend = "setuptools.build_meta"

[project]
name = {json.dumps(project_name)}
version = "1.0.0"
requires-python = ">=3.11,<3.15"
dependencies = {json.dumps(project_requirements)}
{optional_section}
""".lstrip()


def test_prepare_records_validated_project_namespace(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "audit"
    pyproject_path.write_text(_pyproject(), encoding="utf-8")

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((output_dir / "dependency-inputs.json").read_text(encoding="utf-8"))
    assert manifest["project_name"] == "GPT_Quant.Lab"
    assert manifest["canonical_project_name"] == "gpt-quant-lab"


@pytest.mark.parametrize(
    ("location", "requirement"),
    [
        ("build", "gpt_quant_lab>=0"),
        ("project", "GPT.QUANT.LAB==1.0.0"),
        ("optional", "gpt-quant-lab[dev]>=0"),
    ],
)
def test_prepare_rejects_self_dependencies_before_creating_outputs(
    tmp_path: Path,
    location: str,
    requirement: str,
) -> None:
    pyproject_path = tmp_path / f"pyproject-{location}.toml"
    output_dir = tmp_path / f"audit-{location}"
    pyproject_path.write_text(
        _pyproject(requirement=requirement, location=location),
        encoding="utf-8",
    )

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "must not reference the project itself" in completed.stderr
    assert not output_dir.exists()


@pytest.mark.parametrize(
    "project_name",
    ["", " gpt-quant-lab", "gpt/quant/lab"],
)
def test_prepare_rejects_invalid_project_names_before_creating_outputs(
    tmp_path: Path,
    project_name: str,
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "audit"
    pyproject_path.write_text(_pyproject(project_name=project_name), encoding="utf-8")

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "[project].name must be a valid non-empty distribution name" in completed.stderr
    assert not output_dir.exists()
