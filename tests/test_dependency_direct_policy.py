import json
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POLICY_SCRIPT = REPOSITORY_ROOT / "scripts/dependency_audit_direct_policy.py"
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"


def _run_policy(pyproject_path: Path, evidence_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(POLICY_SCRIPT), str(pyproject_path), str(evidence_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def _pyproject_with_requirement(
    requirement: str | None,
    *,
    location: str,
    optional_extra_name: str = "dev",
) -> str:
    build_requirements = ["setuptools>=69"]
    runtime_requirements = ["numpy>=1.26,<3", "pandas>=2.1,<3"]
    optional_requirements = ["pytest>=8,<10", "ruff>=0.9,<1"]
    if requirement is not None:
        if location == "build":
            build_requirements.append(requirement)
        elif location == "runtime":
            runtime_requirements.append(requirement)
        elif location == "optional":
            optional_requirements.append(requirement)
        else:
            raise AssertionError(f"unsupported location: {location}")

    def toml_list(values: list[str]) -> str:
        return ", ".join(json.dumps(value) for value in values)

    return f"""
[build-system]
requires = [{toml_list(build_requirements)}]
build-backend = "setuptools.build_meta"

[project]
name = "direct-policy-test"
version = "1.0.0"
requires-python = ">=3.11,<3.15"
dependencies = [{toml_list(runtime_requirements)}]

[project.optional-dependencies]
{optional_extra_name} = [{toml_list(optional_requirements)}]
""".lstrip()


def test_current_direct_dependencies_are_approved_and_recorded(tmp_path: Path) -> None:
    evidence_path = tmp_path / "security" / "direct-dependency-policy.json"

    completed = _run_policy(PYPROJECT_PATH, evidence_path)

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == {
        "approved_direct_dependencies": {
            "build": ["setuptools"],
            "optional:dev": ["pytest", "ruff"],
            "runtime": ["numpy", "pandas"],
        },
        "declared_direct_dependencies": {
            "build": ["setuptools"],
            "optional:dev": ["pytest", "ruff"],
            "runtime": ["numpy", "pandas"],
        },
        "schema_version": 2,
    }


@pytest.mark.parametrize("location", ["build", "runtime", "optional"])
def test_unapproved_direct_dependency_fails_before_evidence(
    tmp_path: Path,
    location: str,
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    evidence_path = tmp_path / "audit" / "direct-dependency-policy.json"
    pyproject_path.write_text(
        _pyproject_with_requirement("Example_Package>=1", location=location),
        encoding="utf-8",
    )

    completed = _run_policy(pyproject_path, evidence_path)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "unapproved direct dependency names" in completed.stderr
    assert "example-package" in completed.stderr
    assert not evidence_path.parent.exists()


@pytest.mark.parametrize(
    ("requirement", "location", "scope"),
    [
        ("numpy>=1.26", "build", "build"),
        ("setuptools>=69", "runtime", "runtime"),
        ("setuptools>=69", "optional", "optional:dev"),
        ("numpy>=1.26", "optional", "optional:dev"),
    ],
)
def test_approved_name_in_wrong_scope_fails_before_evidence(
    tmp_path: Path,
    requirement: str,
    location: str,
    scope: str,
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    evidence_path = tmp_path / "audit" / "direct-dependency-policy.json"
    pyproject_path.write_text(
        _pyproject_with_requirement(requirement, location=location),
        encoding="utf-8",
    )

    completed = _run_policy(pyproject_path, evidence_path)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert f"'{scope}'" in completed.stderr
    assert not evidence_path.parent.exists()


@pytest.mark.parametrize(
    ("requirement", "location", "label", "canonical_name"),
    [
        ("Setuptools<100", "build", "[build-system].requires", "setuptools"),
        ("NumPy<3", "runtime", "[project].dependencies", "numpy"),
        ("PYTEST<10", "optional", "[project.optional-dependencies].dev", "pytest"),
    ],
)
def test_duplicate_canonical_name_in_one_scope_fails_before_evidence(
    tmp_path: Path,
    requirement: str,
    location: str,
    label: str,
    canonical_name: str,
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    evidence_path = tmp_path / "audit" / "direct-dependency-policy.json"
    pyproject_path.write_text(
        _pyproject_with_requirement(requirement, location=location),
        encoding="utf-8",
    )

    completed = _run_policy(pyproject_path, evidence_path)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert f"{label} must declare each canonical dependency name at most once" in completed.stderr
    assert canonical_name in completed.stderr
    assert not evidence_path.parent.exists()


def test_duplicate_name_cannot_hide_runtime_promotion(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    evidence_path = tmp_path / "audit" / "direct-dependency-policy.json"
    pyproject_path.write_text(
        _pyproject_with_requirement("pytest>=8,<10", location="runtime"),
        encoding="utf-8",
    )

    completed = _run_policy(pyproject_path, evidence_path)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "must not be repeated across declaration scopes" in completed.stderr
    assert "pytest" in completed.stderr
    assert "optional:dev" in completed.stderr
    assert "runtime" in completed.stderr
    assert not evidence_path.parent.exists()


def test_unapproved_optional_scope_fails_before_evidence(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    evidence_path = tmp_path / "audit" / "direct-dependency-policy.json"
    pyproject_path.write_text(
        _pyproject_with_requirement(None, location="runtime", optional_extra_name="qa"),
        encoding="utf-8",
    )

    completed = _run_policy(pyproject_path, evidence_path)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "unapproved direct dependency declaration scopes" in completed.stderr
    assert "optional:qa" in completed.stderr
    assert not evidence_path.parent.exists()


def test_approved_dependency_version_changes_remain_reviewable(tmp_path: Path) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    evidence_path = tmp_path / "audit" / "direct-dependency-policy.json"
    pyproject_path.write_text(
        """
[build-system]
requires = ["setuptools==83.0.0"]
build-backend = "setuptools.build_meta"

[project]
name = "direct-policy-version-test"
version = "1.0.0"
requires-python = ">=3.11,<3.15"
dependencies = ["numpy>=2,<3", "pandas>=2.3,<3"]

[project.optional-dependencies]
dev = ["pytest>=9,<10", "ruff>=0.12,<1"]
""".lstrip(),
        encoding="utf-8",
    )

    completed = _run_policy(pyproject_path, evidence_path)

    assert completed.returncode == 0, completed.stderr
    assert evidence_path.is_file()


def test_trusted_direct_dependency_policy_runs_before_audit_input_creation() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    direct_policy = workflow.index("scripts/dependency_audit_direct_policy.py")
    prepare = workflow.index("scripts/dependency_audit_inputs.py prepare")
    first_install = workflow.index(".resolver-venv/bin/python -m pip install --quiet")

    assert direct_policy < prepare < first_install
    assert "reports/security/direct-dependency-policy.json" in workflow
