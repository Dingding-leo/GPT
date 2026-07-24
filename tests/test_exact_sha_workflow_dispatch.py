from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_ROOT = _REPOSITORY_ROOT / ".github/workflows"
_WORKFLOW_CHECKOUT_COUNTS = {
    "package-build.yml": 1,
    "hourly-research.yml": 1,
    "intraday-1h-research.yml": 2,
    "okx-1h-coverage.yml": 1,
}


def test_g0_workflows_can_verify_one_explicit_immutable_sha() -> None:
    for workflow_name, checkout_count in _WORKFLOW_CHECKOUT_COUNTS.items():
        workflow = (_WORKFLOW_ROOT / workflow_name).read_text(encoding="utf-8")

        assert "workflow_dispatch:" in workflow
        assert "target_sha:" in workflow
        assert "Full 40-character commit SHA to verify" in workflow
        assert "EXPECTED_TESTED_SHA: ${{ inputs.target_sha || github.sha }}" in workflow
        assert workflow.count("ref: ${{ env.EXPECTED_TESTED_SHA }}") == checkout_count
        assert workflow.count("persist-credentials: false") == checkout_count
        assert workflow.count("- name: Verify exact checked-out revision") == checkout_count
        assert workflow.count('[[ "$EXPECTED_TESTED_SHA" =~ ^[0-9a-f]{40}$ ]]') == checkout_count
        assert workflow.count('actual_sha="$(git rev-parse HEAD)"') == checkout_count
        assert workflow.count('test "$actual_sha" = "$EXPECTED_TESTED_SHA"') == checkout_count
        assert "permissions:\n  contents: read" in workflow
        assert "secrets." not in workflow


def test_hourly_release_evidence_binds_the_dispatched_target_sha() -> None:
    workflow = (_WORKFLOW_ROOT / "hourly-research.yml").read_text(encoding="utf-8")

    assert (
        "LIVE_READINESS_HEAD_SHA: ${{ github.event.pull_request.head.sha || "
        "inputs.target_sha || github.sha }}"
    ) in workflow
    assert "LIVE_READINESS_TESTED_SHA: ${{ inputs.target_sha || github.sha }}" in workflow
    assert '--tested-sha "$LIVE_READINESS_TESTED_SHA"' in workflow


def test_exact_sha_dispatch_preserves_public_read_only_boundaries() -> None:
    combined = "\n".join(
        (_WORKFLOW_ROOT / workflow_name).read_text(encoding="utf-8")
        for workflow_name in _WORKFLOW_CHECKOUT_COUNTS
    )

    assert "https://www.okx.com" in combined
    assert "api/v5/account" not in combined
    assert "api/v5/trade/order" not in combined
    assert "private endpoint" not in combined.lower()
