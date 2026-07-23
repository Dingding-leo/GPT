import re
import tomllib
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/package-build.yml"
_PYPROJECT_PATH = _REPOSITORY_ROOT / "pyproject.toml"
_UPLOAD_ARTIFACT_V7 = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def test_package_workflow_builds_sdist_then_verifies_wheel() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    build = workflow.index("- name: Build distributions")
    verify = workflow.index("- name: Verify distributions and wheel environment")
    upload = workflow.index("- name: Upload distributions")
    build_block = workflow[build:verify]
    verify_block = workflow[verify:upload]

    backend_install = build_block.index('"setuptools==${BUILD_BACKEND_VERSION}"')
    build_dependency_check = build_block.index("python -m pip check")
    backend_check = build_block.index('os.environ["BUILD_BACKEND_VERSION"]')
    distribution_build = build_block.index("python -m build --no-isolation")
    wheel_install = verify_block.index(
        '/tmp/gpt-wheel-venv/bin/python -m pip install "${wheels[0]}"'
    )
    dependency_check = verify_block.index("/tmp/gpt-wheel-venv/bin/python -m pip check")
    import_check = verify_block.index("module_path.is_relative_to(venv_path)")

    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert workflow.count('PIP_BOOTSTRAP_VERSION: "26.1.2"') == 1
    assert workflow.count('BUILD_FRONTEND_VERSION: "1.5.0"') == 1
    assert workflow.count('BUILD_BACKEND_VERSION: "83.0.0"') == 1
    assert workflow.count('pip install "pip==${PIP_BOOTSTRAP_VERSION}"') == 2
    assert workflow.count('"build==${BUILD_FRONTEND_VERSION}"') == 1
    assert workflow.count('"setuptools==${BUILD_BACKEND_VERSION}"') == 1
    assert workflow.count("python -m pip check") == 2
    assert workflow.count('os.environ["BUILD_BACKEND_VERSION"]') == 1
    assert workflow.count("python -m build --no-isolation") == 1
    assert "python -m build\n" not in workflow
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
    assert workflow.count(_UPLOAD_ARTIFACT_V7) == 1
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" not in workflow
    assert "gpt-quant-distributions-py${{ matrix.python-version }}" in workflow
    assert "dist/*.tar.gz" in workflow
    assert "dist/*.whl" in workflow
    assert "if-no-files-found: error" in workflow
    assert workflow.count("github.run_attempt") == 1
    assert build < verify < upload
    assert backend_install < build_dependency_check < backend_check < distribution_build
    assert wheel_install < dependency_check < import_check


def test_package_workflow_validates_every_supported_python_version() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    strategy_start = workflow.index("strategy:")
    environment_start = workflow.index("env:", strategy_start)
    strategy_block = workflow[strategy_start:environment_start]

    assert "fail-fast: false" in strategy_block
    assert 'python-version: ["3.11", "3.12", "3.13", "3.14"]' in strategy_block
    assert "python-version: ${{ matrix.python-version }}" in workflow
    assert workflow.count("matrix.python-version") == 2


def test_package_workflow_includes_declared_minimum_python() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    pyproject = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))

    requires_python = pyproject["project"]["requires-python"]
    minimum_match = re.search(r"(?:^|,)>=(\d+\.\d+)(?=,|$)", requires_python)
    assert minimum_match is not None
    minimum_python = minimum_match.group(1)
    ruff_target = pyproject["tool"]["ruff"]["target-version"]

    assert f'python-version: ["{minimum_python}",' in workflow
    assert ruff_target == f"py{minimum_python.replace('.', '')}"
