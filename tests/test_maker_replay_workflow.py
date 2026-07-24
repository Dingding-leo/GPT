from __future__ import annotations

from pathlib import Path

_WORKFLOW = Path(__file__).parents[1] / ".github" / "workflows" / "maker-replay-gate.yml"


def test_maker_replay_workflow_is_offline_and_fail_closed() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in text
    assert "persist-credentials: false" in text
    assert "secrets." not in text
    assert "/api/v5/account" not in text
    assert "/api/v5/trade/order" not in text
    assert "OKX_API_KEY" not in text
    assert "OKX_SECRET" not in text
    assert "OKX_PASSPHRASE" not in text

    expected_order = [
        "Lint and test maker replay gate",
        "Build immutable maker replay evidence",
        "Verify persisted maker replay evidence",
        "Prove deterministic regeneration",
        "Upload immutable maker replay evidence",
    ]
    positions = [text.index(name) for name in expected_order]
    assert positions == sorted(positions)

    assert "tests/test_maker_fill_replay.py" in text
    assert "tests/test_maker_replay_gate.py" in text
    assert "--verify-only" in text
    assert "sha256sum --check artifact-manifest.sha256" in text
    assert 'diff -ru "$EVIDENCE_DIR" "$REBUILT_DIR"' in text
    assert "if-no-files-found: error" in text


def test_maker_replay_workflow_publishes_only_the_persisted_evidence_root() -> None:
    text = _WORKFLOW.read_text(encoding="utf-8")

    assert "EVIDENCE_DIR: reports/paper/maker-replay" in text
    assert "path: ${{ env.EVIDENCE_DIR }}/" in text
    assert "maker-replay-${{ github.run_number }}-attempt-${{ github.run_attempt }}" in text
