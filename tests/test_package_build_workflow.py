from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/package-build.yml"


def test_package_workflow_builds_sdist_then_verifies_wheel() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    build = workflow.index("- name: Build distributions")
    verify = workflow.index("- name: Verify distributions and wheel environment")
    upload = workflow.index("- name: Upload distributions")
    verify_block = workflow[verify:upload]

    wheel_install = verify_block.index(
        '/tmp/gpt-wheel-venv/bin/python -m pip install "${wheels[0]}"'
    )
    dependency_check = verify_block.index("/tmp/gpt-wheel-venv/bin/python -m pip check")
    import_check = verify_block.index("module_path.is_relative_to(venv_path)")

    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert workflow.count('PIP_BOOTSTRAP_VERSION: "26.1.2"') == 1
    assert workflow.count('BUILD_FRONTEND_VERSION: "1.5.0"') == 1
    assert workflow.count('pip install "pip==${PIP_BOOTSTRAP_VERSION}"') == 2
    assert workflow.count('pip install "build==${BUILD_FRONTEND_VERSION}"') == 1
    assert "python -m build\n" in workflow
    assert "python -m build --" not in workflow
    assert "python -m pip wheel ." not in workflow
    assert "pip install -e" not in workflow
    assert "sdists=(dist/gpt_quant_lab-*.tar.gz)" in workflow
    assert "wheels=(dist/gpt_quant_lab-*.whl)" in workflow
    assert 'test "${#sdists[@]}" -eq 1' in workflow
    assert 'test "${#wheels[@]}" -eq 1' in workflow
    assert 'tar -tzf "${sdists[0]}"' in verify_block
    assert "'/pyproject\\.toml$'" in verify_block
    assert "'/src/gpt_quant/__init__\\.py$'" in verify_block
    assert 'Path("/tmp/gpt-wheel-venv").resolve()' in verify_block
    assert "gpt-quant-distributions-${{ github.run_number }}" in workflow
    assert "dist/*.tar.gz" in workflow
    assert "dist/*.whl" in workflow
    assert "if-no-files-found: error" in workflow
    assert workflow.count("github.run_attempt") == 1
    assert build < verify < upload
    assert wheel_install < dependency_check < import_check
