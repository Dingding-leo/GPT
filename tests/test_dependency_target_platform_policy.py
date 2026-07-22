from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"


def test_dependency_audit_resolves_representative_target_wheels() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    expected_targets = {
        "linux-x86_64": "manylinux_2_28_x86_64",
        "linux-aarch64": "manylinux_2_28_aarch64",
        "windows-x86_64": "win_amd64",
        "macos-x86_64": "macosx_11_0_x86_64",
        "macos-arm64": "macosx_11_0_arm64",
    }
    for name, platform in expected_targets.items():
        assert f"- name: {name}\n            platform: {platform}" in workflow

    job_name = (
        "name: Python ${{ matrix.python-version }} / ${{ matrix.target.name }} dependency audit"
    )
    assert job_name in workflow
    assert "AUDIT_PYTHON_VERSION: ${{ matrix.python-version }}" in workflow
    assert "TARGET_NAME: ${{ matrix.target.name }}" in workflow
    assert "TARGET_PLATFORM: ${{ matrix.target.platform }}" in workflow
    assert workflow.count('--python-version "${AUDIT_PYTHON_VERSION}"') == 1
    assert workflow.count("--implementation cp") == 1
    assert workflow.count('--abi "cp${python_tag}"') == 1
    assert workflow.count("--abi abi3") == 1
    assert workflow.count("--abi none") == 1
    assert workflow.count('"${target_args[@]}"') == 2


def test_manylinux_resolution_includes_compatible_platform_tags() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert 'if [[ "${TARGET_PLATFORM}" == manylinux_2_28_* ]]' in workflow
    assert 'architecture="${TARGET_PLATFORM#manylinux_2_28_}"' in workflow
    assert "for minor in $(seq 28 -1 5); do" in workflow
    assert 'target_args+=(--platform "manylinux_2_${minor}_${architecture}")' in workflow
    assert 'target_args+=(--platform "manylinux2014_${architecture}")' in workflow
    legacy_x86_tags = "target_args+=(--platform manylinux2010_x86_64 --platform manylinux1_x86_64)"
    assert legacy_x86_tags in workflow
    assert 'target_args+=(--platform "${TARGET_PLATFORM}")' in workflow


def test_target_platform_is_persisted_in_evidence() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert '"audit_python_version": os.environ["AUDIT_PYTHON_VERSION"]' in workflow
    assert '"target_name": os.environ["TARGET_NAME"]' in workflow
    assert '"target_platform": os.environ["TARGET_PLATFORM"]' in workflow
    artifact_name = (
        "python-dependency-audit-pr${{ github.event.pull_request.number }}-"
        "py${{ matrix.python-version }}-${{ matrix.target.name }}-"
        "${{ github.run_attempt }}"
    )
    assert artifact_name in workflow
