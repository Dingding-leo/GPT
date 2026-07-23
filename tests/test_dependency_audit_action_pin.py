from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"
_UPLOAD_ARTIFACT_V7 = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
_UPLOAD_ARTIFACT_V6 = "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f"


def test_dependency_audit_uses_current_pinned_artifact_uploader() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow.count(_UPLOAD_ARTIFACT_V7) == 1
    assert _UPLOAD_ARTIFACT_V6 not in workflow
    assert "# v7.0.1" in workflow
