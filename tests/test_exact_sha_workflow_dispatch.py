import os
import subprocess
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_ROOT = _REPOSITORY_ROOT / ".github/workflows"
_WORKFLOW_CHECKOUT_COUNTS = {
    "package-build.yml": 1,
    "hourly-research.yml": 1,
    "intraday-1h-research.yml": 2,
    "okx-1h-coverage.yml": 1,
}
_RESOLVED_SHA = "inputs.target_sha || github.event.pull_request.head.sha || github.sha"
_EXPECTED_SHA_BINDING = f"EXPECTED_TESTED_SHA: ${{{{ {_RESOLVED_SHA} }}}}"
_REQUESTED_TARGET_BINDING = "REQUESTED_TARGET_SHA: ${{ inputs.target_sha || '' }}"
_DISPATCH_REF_BINDING = "DISPATCH_REF_SHA: ${{ github.sha }}"


def test_g0_workflows_can_verify_one_explicit_immutable_sha() -> None:
    for workflow_name, checkout_count in _WORKFLOW_CHECKOUT_COUNTS.items():
        workflow = (_WORKFLOW_ROOT / workflow_name).read_text(encoding="utf-8")

        assert "workflow_dispatch:" in workflow
        assert "target_sha:" in workflow
        assert "Full 40-character commit SHA to verify" in workflow
        assert workflow.count(_EXPECTED_SHA_BINDING) == checkout_count
        assert workflow.count(_REQUESTED_TARGET_BINDING) == checkout_count
        assert workflow.count(_DISPATCH_REF_BINDING) == checkout_count
        assert workflow.count("ref: ${{ env.EXPECTED_TESTED_SHA }}") == checkout_count
        assert workflow.count("fetch-depth: 0") == checkout_count
        assert workflow.count("persist-credentials: false") == checkout_count
        assert workflow.count("- name: Verify exact checked-out revision") == checkout_count
        assert workflow.count('[[ "$EXPECTED_TESTED_SHA" =~ ^[0-9a-f]{40}$ ]]') == checkout_count
        assert workflow.count('actual_sha="$(git rev-parse HEAD)"') == checkout_count
        assert workflow.count('test "$actual_sha" = "$EXPECTED_TESTED_SHA"') == checkout_count
        assert workflow.count('if [[ -n "$REQUESTED_TARGET_SHA" ]]; then') == checkout_count
        assert workflow.count('test "$GITHUB_EVENT_NAME" = "workflow_dispatch"') == checkout_count
        assert workflow.count('test "$GITHUB_REF" = "refs/heads/main"') == checkout_count
        assert (
            workflow.count('test "$REQUESTED_TARGET_SHA" = "$EXPECTED_TESTED_SHA"')
            == checkout_count
        )
        assert workflow.count('git cat-file -e "${DISPATCH_REF_SHA}^{commit}"') == checkout_count
        assert (
            workflow.count(
                'git merge-base --is-ancestor "$EXPECTED_TESTED_SHA" "$DISPATCH_REF_SHA"'
            )
            == checkout_count
        )
        assert "permissions:\n  contents: read" in workflow
        assert "secrets." not in workflow


def test_pull_request_runs_bind_to_the_head_commit_not_the_synthetic_merge_commit() -> None:
    for workflow_name in _WORKFLOW_CHECKOUT_COUNTS:
        workflow = (_WORKFLOW_ROOT / workflow_name).read_text(encoding="utf-8")

        assert _RESOLVED_SHA in workflow
        assert "EXPECTED_TESTED_SHA: ${{ inputs.target_sha || github.sha }}" not in workflow


def test_explicit_target_must_be_ancestor_of_main_dispatch_ref(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            capture_output=True,
            check=True,
            text=True,
        )
        return result.stdout.strip()

    git("init")
    git("config", "user.email", "ci@example.invalid")
    git("config", "user.name", "CI Test")
    git("checkout", "-b", "main")
    (repo / "evidence.txt").write_text("base\n", encoding="utf-8")
    git("add", "evidence.txt")
    git("commit", "-m", "base")
    base_sha = git("rev-parse", "HEAD")

    (repo / "evidence.txt").write_text("base\nmain\n", encoding="utf-8")
    git("commit", "-am", "main tip")
    main_tip_sha = git("rev-parse", "HEAD")

    git("checkout", "-b", "unmerged-candidate", base_sha)
    (repo / "candidate.txt").write_text("not merged\n", encoding="utf-8")
    git("add", "candidate.txt")
    git("commit", "-m", "unmerged candidate")
    non_ancestor_sha = git("rev-parse", "HEAD")

    validation_script = r"""
set -euo pipefail
[[ "$EXPECTED_TESTED_SHA" =~ ^[0-9a-f]{40}$ ]]
actual_sha="$(git rev-parse HEAD)"
test "$actual_sha" = "$EXPECTED_TESTED_SHA"
if [[ -n "$REQUESTED_TARGET_SHA" ]]; then
  test "$GITHUB_EVENT_NAME" = "workflow_dispatch"
  test "$GITHUB_REF" = "refs/heads/main"
  test "$REQUESTED_TARGET_SHA" = "$EXPECTED_TESTED_SHA"
  [[ "$DISPATCH_REF_SHA" =~ ^[0-9a-f]{40}$ ]]
  git cat-file -e "${DISPATCH_REF_SHA}^{commit}"
  git merge-base --is-ancestor "$EXPECTED_TESTED_SHA" "$DISPATCH_REF_SHA"
fi
"""

    def run_validation(
        candidate_sha: str,
        *,
        event_name: str = "workflow_dispatch",
        github_ref: str = "refs/heads/main",
    ) -> subprocess.CompletedProcess[str]:
        git("checkout", "--detach", candidate_sha)
        env = os.environ.copy()
        env.update(
            {
                "EXPECTED_TESTED_SHA": candidate_sha,
                "REQUESTED_TARGET_SHA": candidate_sha,
                "DISPATCH_REF_SHA": main_tip_sha,
                "GITHUB_EVENT_NAME": event_name,
                "GITHUB_REF": github_ref,
            }
        )
        return subprocess.run(
            ["bash", "-c", validation_script],
            cwd=repo,
            capture_output=True,
            check=False,
            env=env,
            text=True,
        )

    exact_tip = run_validation(main_tip_sha)
    assert exact_tip.returncode == 0, exact_tip.stderr

    ancestor = run_validation(base_sha)
    assert ancestor.returncode == 0, ancestor.stderr

    non_ancestor = run_validation(non_ancestor_sha)
    assert non_ancestor.returncode != 0

    lookalike_ref = run_validation(base_sha, github_ref="refs/heads/main-shadow")
    assert lookalike_ref.returncode != 0

    wrong_event = run_validation(base_sha, event_name="pull_request")
    assert wrong_event.returncode != 0


def test_hourly_release_evidence_separates_current_head_from_tested_target() -> None:
    workflow = (_WORKFLOW_ROOT / "hourly-research.yml").read_text(encoding="utf-8")
    head_binding = "${{ github.event.pull_request.head.sha || github.sha }}"
    tested_binding = "${{ inputs.target_sha || github.event.pull_request.head.sha || github.sha }}"

    assert f"LIVE_READINESS_HEAD_SHA: {head_binding}" in workflow
    assert f"LIVE_READINESS_TESTED_SHA: {tested_binding}" in workflow
    assert "LIVE_READINESS_HEAD_SHA: ${{ inputs.target_sha ||" not in workflow
    assert '--tested-sha "$LIVE_READINESS_TESTED_SHA"' in workflow


def test_coverage_artifact_persists_validated_tested_sha() -> None:
    workflow = (_WORKFLOW_ROOT / "okx-1h-coverage.yml").read_text(encoding="utf-8")
    sidecar = "reports/okx/1h-coverage/tested-sha.txt"
    write_marker = "printf '%s\\n' \"$EXPECTED_TESTED_SHA\""
    upload_marker = "- name: Upload immutable OKX 1H source evidence"

    assert write_marker in workflow
    assert f"> {sidecar}" in workflow
    assert f'test "$(wc -l < {sidecar})" -eq 1' in workflow
    assert "grep -Eq '^[0-9a-f]{40}$' " + sidecar in workflow
    assert f'test "$(cat {sidecar})" = "$EXPECTED_TESTED_SHA"' in workflow
    assert workflow.index(write_marker) < workflow.index(upload_marker)


def test_coverage_sha_sidecar_rejects_exact_boundary_corruption(tmp_path: Path) -> None:
    output_dir = tmp_path / "coverage"
    output_dir.mkdir()
    validation_script = r"""
set -euo pipefail
printf '%s\n' "$EXPECTED_TESTED_SHA" > "$OUTPUT_DIR/tested-sha.txt"
test "$(wc -l < "$OUTPUT_DIR/tested-sha.txt")" -eq 1
grep -Eq '^[0-9a-f]{40}$' "$OUTPUT_DIR/tested-sha.txt"
test "$(cat "$OUTPUT_DIR/tested-sha.txt")" = "$EXPECTED_TESTED_SHA"
"""
    env = os.environ.copy()
    env["OUTPUT_DIR"] = str(output_dir)

    def run_validation(candidate: str) -> subprocess.CompletedProcess[str]:
        env["EXPECTED_TESTED_SHA"] = candidate
        return subprocess.run(
            ["bash", "-c", validation_script],
            capture_output=True,
            check=False,
            env=env,
            text=True,
        )

    valid_sha = "a" * 40
    valid = run_validation(valid_sha)
    assert valid.returncode == 0, valid.stderr
    assert (output_dir / "tested-sha.txt").read_bytes() == f"{valid_sha}\n".encode()

    corrupt_candidates = {
        "one_character_short": "a" * 39,
        "one_character_long": "a" * 41,
        "uppercase": "A" * 40,
        "embedded_newline": f"{'a' * 20}\n{'a' * 20}",
    }
    for boundary, candidate in corrupt_candidates.items():
        result = run_validation(candidate)
        assert result.returncode != 0, boundary


def test_exact_sha_dispatch_preserves_public_read_only_boundaries() -> None:
    combined = "\n".join(
        (_WORKFLOW_ROOT / workflow_name).read_text(encoding="utf-8")
        for workflow_name in _WORKFLOW_CHECKOUT_COUNTS
    )

    assert "https://www.okx.com" in combined
    assert "api/v5/account" not in combined
    assert "api/v5/trade/order" not in combined
    assert "private endpoint" not in combined.lower()
