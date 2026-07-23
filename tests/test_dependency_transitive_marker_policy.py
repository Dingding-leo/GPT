import json
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
POLICY_SCRIPT = REPOSITORY_ROOT / "scripts" / "dependency_audit_transitive.py"


def _run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(POLICY_SCRIPT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )


def _item(
    name: str,
    version: str,
    *,
    requires_dist: list[str] | None = None,
    sha: str = "a" * 64,
) -> dict[str, object]:
    metadata: dict[str, object] = {"name": name, "version": version}
    if requires_dist is not None:
        metadata["requires_dist"] = requires_dist
    return {
        "is_direct": False,
        "metadata": metadata,
        "download_info": {
            "url": f"https://files.pythonhosted.org/packages/{name}-{version}.whl",
            "archive_info": {"hashes": {"sha256": sha}},
        },
    }


def _write_report(path: Path, items: list[dict[str, object]]) -> None:
    path.write_text(json.dumps({"install": items}), encoding="utf-8")


def test_collects_and_verifies_transitive_platform_dependency_closure(tmp_path: Path) -> None:
    initial = tmp_path / "initial.json"
    promoted = tmp_path / "platform-requirements.in"
    final = tmp_path / "final.json"
    _write_report(
        initial,
        [
            _item(
                "pytest",
                "9.0.2",
                requires_dist=['colorama>=0.4; sys_platform == "win32"'],
            )
        ],
    )

    collected = _run("collect", str(initial), str(promoted))

    assert collected.returncode == 0, collected.stderr
    assert promoted.read_text(encoding="utf-8") == "colorama>=0.4\n"

    _write_report(
        final,
        [
            _item(
                "pytest",
                "9.0.2",
                requires_dist=['colorama>=0.4; sys_platform == "win32"'],
            ),
            _item("colorama", "0.4.6", requires_dist=[]),
        ],
    )
    verified = _run("verify", str(final), str(promoted))

    assert verified.returncode == 0, verified.stderr


def test_verify_rejects_new_nested_platform_dependency(tmp_path: Path) -> None:
    promoted = tmp_path / "platform-requirements.in"
    promoted.write_text("colorama>=0.4\n", encoding="utf-8")
    final = tmp_path / "final.json"
    _write_report(
        final,
        [
            _item(
                "pytest",
                "9.0.2",
                requires_dist=['colorama>=0.4; sys_platform == "win32"'],
            ),
            _item(
                "colorama",
                "0.4.6",
                requires_dist=['win-helper>=1; platform_system == "Windows"'],
            ),
        ],
    )

    completed = _run("verify", str(final), str(promoted))

    assert completed.returncode == 2
    assert "closure changed after promotion" in completed.stderr


def test_collect_ignores_inactive_extra_gated_platform_requirement(tmp_path: Path) -> None:
    report = tmp_path / "resolution.json"
    output = tmp_path / "platform-requirements.in"
    _write_report(
        report,
        [
            _item(
                "setuptools",
                "83.0.0",
                requires_dist=[
                    'pytest-perf; sys_platform != "cygwin" and extra == "test"',
                    'jaraco.develop>=7.21; (python_version >= "3.11" and '
                    'sys_platform != "cygwin") and extra == "test"',
                ],
            )
        ],
    )

    completed = _run("collect", str(report), str(output))

    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == ""


@pytest.mark.parametrize(
    "requirement",
    [
        'default-helper>=1; extra == "" and sys_platform == "win32"',
        "default-helper>=1; platform_system == 'Windows' and extra == ''",
    ],
)
def test_collect_promotes_platform_requirement_active_for_default_extra(
    tmp_path: Path,
    requirement: str,
) -> None:
    report = tmp_path / "resolution.json"
    output = tmp_path / "platform-requirements.in"
    _write_report(
        report,
        [_item("example", "1.0", requires_dist=[requirement])],
    )

    completed = _run("collect", str(report), str(output))

    assert completed.returncode == 0, completed.stderr
    assert output.read_text(encoding="utf-8") == "default-helper>=1\n"


@pytest.mark.parametrize(
    "requirement",
    [
        "requests[socks]>=2",
        'requests[socks]>=2; sys_platform == "win32"',
    ],
)
def test_validate_manifest_rejects_requested_third_party_extras(
    tmp_path: Path,
    requirement: str,
) -> None:
    manifest = tmp_path / "dependency-inputs.json"
    manifest.write_text(
        json.dumps(
            {
                "build_requirements": ["setuptools>=69"],
                "project_requirements": [requirement],
            }
        ),
        encoding="utf-8",
    )

    completed = _run("validate-manifest", str(manifest))

    assert completed.returncode == 2
    assert "third-party dependency extras are not allowed" in completed.stderr


def test_collect_rejects_unconditional_transitive_extra_request(tmp_path: Path) -> None:
    report = tmp_path / "resolution.json"
    output = tmp_path / "platform-requirements.in"
    _write_report(
        report,
        [_item("example", "1.0", requires_dist=["requests[socks]>=2"])],
    )

    completed = _run("collect", str(report), str(output))

    assert completed.returncode == 2
    assert "transitive dependency extras are not allowed" in completed.stderr
    assert not output.exists()
