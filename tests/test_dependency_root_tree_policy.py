import json
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts" / "dependency_audit_root_tree.py"
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "dependency-review.yml"


def _entry(name: str, *, entry_type: str = "file", path: str | None = None) -> dict[str, str]:
    return {"name": name, "path": name if path is None else path, "type": entry_type}


def _run_policy(tmp_path: Path, contents: object) -> subprocess.CompletedProcess[str]:
    contents_path = tmp_path / "proposed-root-contents.json"
    contents_path.write_text(json.dumps(contents), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(contents_path)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_root_tree_policy_accepts_safe_exact_root_listing(tmp_path: Path) -> None:
    completed = _run_policy(
        tmp_path,
        [_entry("README.md"), _entry("pyproject.toml"), _entry("src", entry_type="dir")],
    )

    assert completed.returncode == 0
    assert completed.stderr == ""


@pytest.mark.parametrize("name", ["Setup.py", "SETUP.PY", "Setup.Cfg", "SETUP.CFG"])
def test_root_tree_policy_rejects_casefolded_legacy_build_files(
    tmp_path: Path,
    name: str,
) -> None:
    completed = _run_policy(tmp_path, [_entry("pyproject.toml"), _entry(name)])

    assert completed.returncode == 2
    assert f"legacy setuptools file is not allowed: {name}" in completed.stderr
    assert not (tmp_path / "dependency-inputs.json").exists()


@pytest.mark.parametrize(
    "contents",
    [
        {},
        ["README.md"],
        [_entry("README.md", path="nested/README.md")],
        [{"name": "README.md", "path": "README.md"}],
        [_entry(f"file-{index}") for index in range(1000)],
    ],
)
def test_root_tree_policy_rejects_malformed_or_incomplete_evidence(
    tmp_path: Path,
    contents: object,
) -> None:
    completed = _run_policy(tmp_path, contents)

    assert completed.returncode == 2
    assert "dependency audit root-tree error:" in completed.stderr


def test_trusted_workflow_validates_casefolded_root_before_resolution() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    root_download = workflow.index("proposed-root-contents.json")
    root_validation = workflow.index("dependency_audit_root_tree.py")
    exact_status_validation = workflow.index("validate-legacy-build-files")
    preparation = workflow.index("dependency_audit_inputs.py prepare")
    resolution = workflow.index("- name: Resolve proposed dependencies without installation")

    assert "contents?ref=${HEAD_SHA}" in workflow
    assert "Accept: application/vnd.github+json" in workflow
    assert root_download < root_validation < exact_status_validation < preparation < resolution
    assert all(
        path.name.casefold() not in {"setup.py", "setup.cfg"}
        for path in REPOSITORY_ROOT.iterdir()
    )
