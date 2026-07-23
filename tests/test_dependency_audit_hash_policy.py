import json
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
AUDIT_INPUT_SCRIPT = REPOSITORY_ROOT / "scripts/dependency_audit_inputs.py"


def _write_resolution_report(path: Path, sha256: object) -> None:
    path.write_text(
        json.dumps(
            {
                "install": [
                    {
                        "is_direct": False,
                        "metadata": {"name": "Example_Package", "version": "1.2.3"},
                        "download_info": {
                            "url": "https://files.pythonhosted.org/packages/example.whl",
                            "archive_info": {"hashes": {"sha256": sha256}},
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def _lock_report(
    report_path: Path,
    requirements_path: Path,
    evidence_path: Path,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(AUDIT_INPUT_SCRIPT),
            "lock-report",
            str(report_path),
            str(requirements_path),
            str(evidence_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "malformed_sha256",
    [
        "g" * 64,
        "a" * 63,
        "a" * 65,
        7,
    ],
)
def test_lock_report_rejects_malformed_artifact_sha256(
    tmp_path: Path,
    malformed_sha256: object,
) -> None:
    report_path = tmp_path / "resolution.json"
    requirements_path = tmp_path / "resolved.txt"
    evidence_path = tmp_path / "artifacts.json"
    _write_resolution_report(report_path, malformed_sha256)

    completed = _lock_report(report_path, requirements_path, evidence_path)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "valid artifact SHA-256" in completed.stderr
    assert not requirements_path.exists()
    assert not evidence_path.exists()


def test_lock_report_canonicalizes_valid_artifact_sha256(tmp_path: Path) -> None:
    report_path = tmp_path / "resolution.json"
    requirements_path = tmp_path / "resolved.txt"
    evidence_path = tmp_path / "artifacts.json"
    _write_resolution_report(report_path, "A" * 64)

    completed = _lock_report(report_path, requirements_path, evidence_path)

    assert completed.returncode == 0, completed.stderr
    assert requirements_path.read_text(encoding="utf-8") == "Example_Package==1.2.3\n"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence[0]["sha256"] == "a" * 64
