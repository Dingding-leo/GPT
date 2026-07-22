import json
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "dependency_audit_inputs.py"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "dependency-review.yml"
FORBIDDEN_FILES = ("setup.py", "setup.cfg")


def _run_policy(tmp_path: Path, statuses: object) -> subprocess.CompletedProcess[str]:
    status_path = tmp_path / "legacy-build-files.json"
    status_path.write_text(json.dumps(statuses), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "validate-legacy-build-files",
            str(status_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_legacy_build_policy_accepts_absent_files(tmp_path: Path) -> None:
    completed = _run_policy(tmp_path, {path: 404 for path in FORBIDDEN_FILES})

    assert completed.returncode == 0
    assert completed.stderr == ""


@pytest.mark.parametrize("path", FORBIDDEN_FILES)
def test_legacy_build_policy_rejects_present_setuptools_file(
    tmp_path: Path,
    path: str,
) -> None:
    statuses = {name: 404 for name in FORBIDDEN_FILES}
    statuses[path] = 200

    completed = _run_policy(tmp_path, statuses)

    assert completed.returncode == 2
    assert f"legacy setuptools file is not allowed: {path}" in completed.stderr


@pytest.mark.parametrize("status", [0, 301, 403, 500])
def test_legacy_build_policy_fails_closed_on_unverified_status(
    tmp_path: Path,
    status: int,
) -> None:
    completed = _run_policy(
        tmp_path,
        {"setup.py": status, "setup.cfg": 404},
    )

    assert completed.returncode == 2
    assert f"unable to verify absence of legacy setuptools file setup.py: HTTP {status}" in (
        completed.stderr
    )


@pytest.mark.parametrize(
    "statuses",
    [
        {},
        {"setup.py": 404},
        {"setup.py": 404, "setup.cfg": 404, "extra": 404},
        {"setup.py": "404", "setup.cfg": 404},
        {"setup.py": True, "setup.cfg": 404},
    ],
)
def test_legacy_build_policy_rejects_malformed_evidence(
    tmp_path: Path,
    statuses: object,
) -> None:
    completed = _run_policy(tmp_path, statuses)

    assert completed.returncode == 2
    assert "dependency audit input error:" in completed.stderr


def test_trusted_workflow_checks_legacy_build_files_before_resolution() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    validation = workflow.index("validate-legacy-build-files")
    preparation = workflow.index("dependency_audit_inputs.py prepare")
    resolution = workflow.index("- name: Resolve proposed dependencies without installation")

    assert "contents/${path}?ref=${HEAD_SHA}" in workflow
    assert "for path in setup.py setup.cfg; do" in workflow
    assert "legacy-build-files.json" in workflow
    assert validation < preparation < resolution
    assert not (REPOSITORY_ROOT / "setup.py").exists()
    assert not (REPOSITORY_ROOT / "setup.cfg").exists()
