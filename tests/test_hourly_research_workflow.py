from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/hourly-research.yml"


def test_hourly_workflow_pins_pip_before_project_install() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    version_declaration = 'PIP_BOOTSTRAP_VERSION: "26.1.2"'
    pinned_install = 'python -m pip install "pip==${PIP_BOOTSTRAP_VERSION}"'
    project_install = 'python -m pip install -e ".[dev]"'

    assert workflow.count(version_declaration) == 1
    assert workflow.count(pinned_install) == 1
    assert "pip install --upgrade pip" not in workflow
    assert workflow.index(version_declaration) < workflow.index(pinned_install)
    assert workflow.index(pinned_install) < workflow.index(project_install)


def test_hourly_workflow_publishes_portfolio_from_source_artifact_evidence() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    research = workflow.index("- name: Run OKX rolling out-of-sample research")
    hashes = workflow.index("- name: Hash portfolio return inputs")
    source_upload = workflow.index("- name: Upload immutable sleeve research source")
    portfolio = workflow.index("- name: Generate verified portfolio risk report")
    portfolio_upload = workflow.index("- name: Upload verified portfolio risk artifact")

    assert research < hashes < source_upload < portfolio < portfolio_upload
    assert workflow.count("id: source-artifact") == 1
    assert workflow.count("id: return-hashes") == 1
    assert "steps.source-artifact.outputs.artifact-id" in workflow
    assert "steps.source-artifact.outputs.artifact-digest" in workflow
    assert "steps.return-hashes.outputs.btc_sha256" in workflow
    assert "steps.return-hashes.outputs.eth_sha256" in workflow
    assert (
        'SOURCE_ARTIFACT_NAME: "quant-research-source-${{ github.run_number }}-attempt-'
        '${{ github.run_attempt }}"' in workflow
    )
    assert (
        'PORTFOLIO_ARTIFACT_NAME: "quant-portfolio-risk-${{ github.run_number }}-attempt-'
        '${{ github.run_attempt }}"' in workflow
    )
    assert workflow.count("github.run_attempt") == 2
    assert 'sha256sum "$btc_returns"' in workflow
    assert 'sha256sum "$eth_returns"' in workflow
    assert '--source-workflow-run "$GITHUB_RUN_ID"' in workflow
    assert '--source-artifact-id "$SOURCE_ARTIFACT_ID"' in workflow
    assert '--source-artifact-name "$SOURCE_ARTIFACT_NAME"' in workflow
    assert '--source-artifact-sha256 "$source_artifact_digest"' in workflow
    assert '--source-head-sha "$GITHUB_SHA"' in workflow
    assert "path: reports/okx/" in workflow
    assert "path: reports/portfolio/" in workflow
