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


def _pyproject(project_extra: str = "", setuptools_extra: str = "") -> str:
    return f"""
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "dynamic-metadata-policy-test"
version = "1.0.0"
requires-python = ">=3.11,<3.15"
dependencies = ["numpy>=1.26,<3"]
{project_extra}

[tool.setuptools.packages.find]
where = ["src"]
{setuptools_extra}
""".lstrip()


def test_prepare_accepts_static_setuptools_metadata(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "audit"
    pyproject_path.write_text(_pyproject("dynamic = []"), encoding="utf-8")

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((output_dir / "dependency-inputs.json").read_text(encoding="utf-8"))
    assert manifest["project_name"] == "dynamic-metadata-policy-test"


@pytest.mark.parametrize("field", ["version", "readme", "classifiers"])
def test_prepare_rejects_dynamic_project_metadata_before_output(
    tmp_path: Path,
    field: str,
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "audit"
    contents = _pyproject(f'dynamic = ["{field}"]')
    if field == "version":
        contents = contents.replace('version = "1.0.0"\n', "")
    pyproject_path.write_text(contents, encoding="utf-8")

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "dynamic project metadata is not allowed" in completed.stderr
    assert not output_dir.exists()


def test_prepare_rejects_setuptools_dynamic_table_before_output(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "audit"
    pyproject_path.write_text(
        _pyproject(
            "dynamic = []",
            '\n[tool.setuptools.dynamic]\nversion = {attr = "package.__version__"}',
        ),
        encoding="utf-8",
    )

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "[tool.setuptools.dynamic] is not allowed" in completed.stderr
    assert not output_dir.exists()
