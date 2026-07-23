from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/hourly-research.yml"


def test_hourly_workflow_pins_and_validates_install_before_quality_gates() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    version_declaration = 'PIP_BOOTSTRAP_VERSION: "26.1.2"'
    pinned_install = 'python -m pip install "pip==${PIP_BOOTSTRAP_VERSION}"'
    project_install = 'python -m pip install -e ".[dev]"'
    dependency_check = "python -m pip check"
    lint_step = "- name: Lint and formatting"

    assert workflow.count(version_declaration) == 1
    assert workflow.count(pinned_install) == 1
    assert workflow.count(dependency_check) == 1
    assert "pip install --upgrade pip" not in workflow
    assert workflow.index(version_declaration) < workflow.index(pinned_install)
    assert workflow.index(pinned_install) < workflow.index(project_install)
    assert workflow.index(project_install) < workflow.index(dependency_check)
    assert workflow.index(dependency_check) < workflow.index(lint_step)


def test_hourly_workflow_scopes_concurrency_by_event_and_ref() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    concurrency_start = workflow.index("concurrency:")
    jobs_start = workflow.index("jobs:")
    concurrency_block = workflow[concurrency_start:jobs_start]

    assert concurrency_block.count("github.event_name") == 1
    assert concurrency_block.count("github.ref") == 1
    assert (
        "group: hourly-quant-research-${{ github.event_name }}-${{ github.ref }}"
        in concurrency_block
    )
    assert "cancel-in-progress: true" in concurrency_block


def test_hourly_workflow_publishes_portfolio_from_source_artifact_evidence() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    research = workflow.index("- name: Run OKX rolling out-of-sample research")
    verification = workflow.index("- name: Verify persisted walk-forward evidence")
    hashes = workflow.index("- name: Hash portfolio return inputs")
    source_upload = workflow.index("- name: Upload immutable sleeve research source")
    portfolio = workflow.index("- name: Generate verified portfolio risk report")
    portfolio_upload = workflow.index("- name: Upload verified portfolio risk artifact")

    assert research < verification < hashes < source_upload < portfolio < portfolio_upload
    assert workflow.count("python scripts/verify_walk_forward_report.py") == 1
    assert '--output-dir "reports/okx/$instrument"' in workflow
    assert workflow.count("--manifest-path reports/okx/experiment-manifest.jsonl") == 2
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
    assert '--max-variance-contribution "$MAX_VARIANCE_CONTRIBUTION"' in workflow
    assert "path: reports/okx/" in workflow
    assert "path: reports/portfolio/" in workflow


def test_hourly_workflow_never_publishes_rejected_portfolio_as_verified() -> None:
    workflow = _WORKFLOW_PATH.read_text(encoding="utf-8")

    generation = workflow.index("- name: Generate verified portfolio risk report")
    upload = workflow.index("- name: Upload verified portfolio risk artifact")
    upload_block = workflow[upload:]

    assert generation < upload
    assert "--fail-on-reject" in workflow[generation:upload]
    assert (
        "if: ${{ success() && hashFiles('reports/portfolio/portfolio_risk.json') != '' }}"
        in upload_block
    )
    assert "always()" not in upload_block
