import ast
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"
PYPROJECT_PATH = REPOSITORY_ROOT / "pyproject.toml"
AUDIT_INPUT_SCRIPT = REPOSITORY_ROOT / "scripts/dependency_audit_inputs.py"


def _run_script(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(AUDIT_INPUT_SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _pip_install_commands(workflow: str) -> list[str]:
    commands: list[str] = []
    current: list[str] = []
    for raw_line in workflow.splitlines():
        line = raw_line.strip()
        if not current and "-m pip install" not in line:
            continue
        current.append(line.removesuffix("\\").strip())
        if not line.endswith("\\"):
            commands.append(" ".join(current))
            current = []
    assert not current
    return commands


def test_audit_uses_trusted_pull_request_target_policy() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "pull_request_target:" in workflow
    assert "\n  pull_request:\n" not in workflow
    assert workflow.count("actions/checkout@") == 1
    assert "ref: ${{ github.event.pull_request.base.sha }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "secrets." not in workflow
    assert "cache: pip" not in workflow


def test_proposed_head_is_downloaded_as_data_and_never_checked_out() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "HEAD_REPOSITORY: ${{ github.event.pull_request.head.repo.full_name }}" in workflow
    assert "HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in workflow
    assert "Accept: application/vnd.github.raw+json" in workflow
    assert "contents/pyproject.toml?ref=${HEAD_SHA}" in workflow
    assert '--output "${PROPOSED_PYPROJECT}"' in workflow
    assert "ref: ${{ github.event.pull_request.head.sha }}" not in workflow
    assert "github.event.pull_request.head.ref" not in workflow


def test_trusted_validator_runs_before_any_third_party_install() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    download = workflow.index("- name: Download proposed dependency manifest as data")
    validate = workflow.index("- name: Validate proposed dependency declarations")
    first_install = workflow.index(".resolver-venv/bin/python -m pip install --quiet")

    assert download < validate < first_install
    assert workflow.count("scripts/dependency_audit_inputs.py prepare") == 1
    assert "reports/security/proposed-pyproject.toml" in workflow


def test_proposed_repository_code_is_never_installed_or_executed() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "pip install -e" not in workflow
    assert "--no-build-isolation" not in workflow
    assert "pip freeze" not in workflow
    assert "project-install-target" not in workflow
    assert "source " not in workflow


def test_all_pip_operations_are_binary_only_and_use_public_pypi() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    commands = _pip_install_commands(workflow)

    assert len(commands) == 5
    assert all("--only-binary=:all:" in command for command in commands)
    assert all('--index-url "${PYPI_INDEX_URL}"' in command for command in commands)
    assert all("--no-cache-dir" in command for command in commands)
    assert workflow.count('"pip==${PIP_BOOTSTRAP_VERSION}"') == 2
    assert workflow.count('"pip-audit==${PIP_AUDIT_VERSION}"') == 1


def test_audit_matrix_matches_the_bounded_python_support_policy() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    pyproject = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    matrix_line = next(
        line.strip()
        for line in workflow.splitlines()
        if line.strip().startswith("python-version: [")
    )

    assert ast.literal_eval(matrix_line.partition(":")[2].strip()) == [
        "3.11",
        "3.12",
        "3.13",
        "3.14",
    ]
    assert pyproject["project"]["requires-python"] == ">=3.11,<3.15"


def test_both_dependency_sets_are_audited_before_enforcement() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    build_audit = workflow.index("- name: Audit build dependencies")
    project_audit = workflow.index("- name: Audit project dependencies")
    upload = workflow.index("- name: Upload dependency audit evidence")
    enforce = workflow.index("- name: Enforce dependency audits")

    assert build_audit < project_audit < upload < enforce
    assert "if: always()" in workflow[upload:enforce]
    assert "steps.build-audit.outcome == 'failure'" in workflow[enforce:]
    assert "steps.project-audit.outcome == 'failure'" in workflow[enforce:]
    assert "retention-days: 14" in workflow[upload:enforce]


def test_prepare_emits_all_declared_dependencies_and_provenance(tmp_path: Path) -> None:
    output_dir = tmp_path / "audit"
    completed = _run_script("prepare", str(PYPROJECT_PATH), str(output_dir))

    assert completed.returncode == 0, completed.stderr
    manifest = json.loads((output_dir / "dependency-inputs.json").read_text(encoding="utf-8"))
    assert manifest["requires_python"] == ">=3.11,<3.15"
    assert manifest["optional_extras"] == ["dev"]
    assert manifest["build_requirements"] == ["setuptools>=69"]
    assert manifest["project_requirements"] == [
        "numpy>=1.26,<3",
        "pandas>=2.1,<3",
        "pytest>=8,<10",
        "ruff>=0.9,<1",
    ]
    assert len(manifest["source_sha256"]) == 64


@pytest.mark.parametrize(
    "unsafe_requirement",
    [
        "example @ https://example.invalid/example.whl",
        "https://example.invalid/example.whl",
        "git+https://example.invalid/example.git",
        "file:///tmp/example.whl",
        "../example.whl",
        "C:\\example.whl",
        "--extra-index-url=https://example.invalid/simple",
    ],
)
def test_prepare_rejects_non_index_dependency_sources(
    tmp_path: Path,
    unsafe_requirement: str,
) -> None:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        f"""
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "unsafe-source-test"
version = "1.0.0"
requires-python = ">=3.11,<3.15"
dependencies = [{unsafe_requirement!r}]
""".lstrip(),
        encoding="utf-8",
    )

    completed = _run_script("prepare", str(pyproject_path), str(tmp_path / "audit"))

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "unsafe [project].dependencies requirement" in completed.stderr
    assert not (tmp_path / "audit").exists()


def test_prepare_rejects_dynamic_or_colliding_dependency_declarations(tmp_path: Path) -> None:
    cases = (
        """
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "dynamic-test"
version = "1.0.0"
requires-python = ">=3.11,<3.15"
dynamic = ["dependencies"]
""",
        """
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "collision-test"
version = "1.0.0"
requires-python = ">=3.11,<3.15"
dependencies = ["numpy>=1.26"]

[project.optional-dependencies]
foo-bar = []
foo_bar = []
""",
    )

    for index, text in enumerate(cases):
        pyproject_path = tmp_path / f"pyproject-{index}.toml"
        output_dir = tmp_path / f"audit-{index}"
        pyproject_path.write_text(text.lstrip(), encoding="utf-8")
        completed = _run_script("prepare", str(pyproject_path), str(output_dir))
        assert completed.returncode == 2
        assert not output_dir.exists()


def test_lock_report_persists_pinned_pypi_artifact_evidence(tmp_path: Path) -> None:
    report_path = tmp_path / "resolution.json"
    requirements_path = tmp_path / "resolved.txt"
    evidence_path = tmp_path / "artifacts.json"
    report_path.write_text(
        json.dumps(
            {
                "install": [
                    {
                        "is_direct": False,
                        "metadata": {"name": "Example_Package", "version": "1.2.3"},
                        "download_info": {
                            "url": "https://files.pythonhosted.org/packages/example.whl",
                            "archive_info": {"hashes": {"sha256": "a" * 64}},
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = _run_script(
        "lock-report",
        str(report_path),
        str(requirements_path),
        str(evidence_path),
    )

    assert completed.returncode == 0, completed.stderr
    assert requirements_path.read_text(encoding="utf-8") == "Example_Package==1.2.3\n"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence == [
        {
            "name": "Example_Package",
            "sha256": "a" * 64,
            "url": "https://files.pythonhosted.org/packages/example.whl",
            "version": "1.2.3",
        }
    ]


@pytest.mark.parametrize(
    ("is_direct", "url"),
    [
        (True, "https://files.pythonhosted.org/packages/example.whl"),
        (False, "https://example.invalid/example.whl"),
    ],
)
def test_lock_report_rejects_untrusted_resolution_artifacts(
    tmp_path: Path,
    is_direct: bool,
    url: str,
) -> None:
    report_path = tmp_path / "resolution.json"
    report_path.write_text(
        json.dumps(
            {
                "install": [
                    {
                        "is_direct": is_direct,
                        "metadata": {"name": "example", "version": "1.0"},
                        "download_info": {
                            "url": url,
                            "archive_info": {"hashes": {"sha256": "b" * 64}},
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    completed = _run_script(
        "lock-report",
        str(report_path),
        str(tmp_path / "resolved.txt"),
        str(tmp_path / "artifacts.json"),
    )

    assert completed.returncode == 2
    assert not (tmp_path / "resolved.txt").exists()
    assert not (tmp_path / "artifacts.json").exists()
