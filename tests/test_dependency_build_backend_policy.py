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


def _pyproject(build_system_extra: str = "") -> str:
    return f"""
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"
{build_system_extra}

[project]
name = "build-backend-policy-test"
version = "1.0.0"
requires-python = ">=3.11,<3.15"
dependencies = ["numpy>=1.26,<3"]
""".lstrip()


def test_prepare_records_the_trusted_build_backend(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "audit"
    pyproject_path.write_text(_pyproject(), encoding="utf-8")

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((output_dir / "dependency-inputs.json").read_text(encoding="utf-8"))
    assert manifest["build_backend"] == "setuptools.build_meta"


@pytest.mark.parametrize(
    ("trusted_backend", "build_system_extra", "message"),
    [
        (False, "", "build-backend must be exactly 'setuptools.build_meta'"),
        (True, 'backend-path = ["."]', "backend-path is not allowed"),
    ],
)
def test_prepare_rejects_untrusted_build_backend_configuration(
    tmp_path: Path,
    trusted_backend: bool,
    build_system_extra: str,
    message: str,
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    output_dir = tmp_path / "audit"
    contents = _pyproject(build_system_extra)
    if not trusted_backend:
        contents = contents.replace(
            'build-backend = "setuptools.build_meta"',
            'build-backend = "project_local_backend"',
        )
    pyproject_path.write_text(contents, encoding="utf-8")

    completed = _run_prepare(pyproject_path, output_dir)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert message in completed.stderr
    assert not output_dir.exists()
