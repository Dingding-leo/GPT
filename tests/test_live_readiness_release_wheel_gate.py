from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/hourly-research.yml"


def test_live_readiness_install_gate_builds_and_imports_release_wheel() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")
    install_start = workflow.index("- name: Install project")
    lint_start = workflow.index("- name: Lint and formatting")
    install_block = workflow[install_start:lint_start]

    assert 'BUILD_FRONTEND_VERSION: "1.5.0"' in workflow
    assert 'BUILD_BACKEND_VERSION: "83.0.0"' in workflow
    assert "shell: bash" in install_block
    assert "set -euo pipefail" in install_block
    assert '"build==${BUILD_FRONTEND_VERSION}"' in install_block
    assert '"setuptools==${BUILD_BACKEND_VERSION}"' in install_block
    assert "python -m build --wheel --no-isolation" in install_block
    assert 'wheels=(dist/gpt_quant_lab-*.whl)' in install_block
    assert 'test "${#wheels[@]}" -eq 1' in install_block
    assert "python -m venv /tmp/gpt-live-readiness-wheel-venv" in install_block
    assert '/tmp/gpt-live-readiness-wheel-venv/bin/pip install "${wheels[0]}"' in install_block
    assert "/tmp/gpt-live-readiness-wheel-venv/bin/pip check" in install_block
    assert "/tmp/gpt-live-readiness-wheel-venv/bin/python - <<'PY'" in install_block
    assert "gpt_quant imported outside release wheel venv" in install_block
    assert "--no-deps" not in install_block

    build = install_block.index("python -m build --wheel --no-isolation")
    wheel_install = install_block.index(
        '/tmp/gpt-live-readiness-wheel-venv/bin/pip install "${wheels[0]}"'
    )
    wheel_check = install_block.index("/tmp/gpt-live-readiness-wheel-venv/bin/pip check")
    wheel_import = install_block.index("/tmp/gpt-live-readiness-wheel-venv/bin/python - <<'PY'")
    assert build < wheel_install < wheel_check < wheel_import
