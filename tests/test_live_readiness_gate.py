import inspect
import json
from pathlib import Path

import pytest

from gpt_quant import live_readiness

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_safe_workflow(repo_root: Path) -> None:
    workflow = repo_root / ".github/workflows/hourly-research.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        """permissions:
  contents: read
jobs:
  test:
    steps:
      - uses: actions/checkout@0123456789abcdef
        with:
          persist-credentials: false
      - env:
          GH_TOKEN: ${{ github.token }}
        run: echo safe
""",
        encoding="utf-8",
    )


def _successful_ci_checks() -> dict[str, str]:
    return {name: "success" for name in live_readiness._REQUIRED_CI_CHECKS}


def _write_complete_evidence(repo_root: Path, *, head_sha: str) -> None:
    _write_json(
        repo_root / "config/okx_research.json",
        {"strategy": {"transaction_cost_bps": 5.0}},
    )
    _write_safe_workflow(repo_root)
    for _, (relative_path, expected) in live_readiness._REQUIRED_EVIDENCE.items():
        _write_json(repo_root / relative_path, {"head_sha": head_sha, **expected})


def test_live_readiness_gate_reports_current_launch_blockers(tmp_path: Path) -> None:
    head_sha = "a" * 40
    _write_json(
        tmp_path / "config/okx_research.json",
        {"strategy": {"transaction_cost_bps": 10.0}},
    )
    _write_safe_workflow(tmp_path)

    result = live_readiness.evaluate_live_readiness(
        tmp_path,
        head_sha=head_sha,
        tested_sha=head_sha,
        ci_checks=_successful_ci_checks(),
    )

    blocker_codes = {blocker.code for blocker in result.blockers}
    assert not result.ready
    assert result.tested_sha == head_sha
    assert "fee_baseline_not_5bps" in blocker_codes
    assert "missing_five_bps_walk_forward" in blocker_codes
    assert "missing_execution_costs" in blocker_codes
    assert "missing_paper_execution" in blocker_codes
    assert "missing_state_recovery" in blocker_codes
    assert "missing_risk_controls" in blocker_codes
    assert "missing_forward_validation" in blocker_codes
    assert set(result.passed_checks) == {
        "ci_has_no_account_order_or_secret_markers",
        "tested_head_matches_source",
        *(f"ci_{name}" for name in live_readiness._REQUIRED_CI_CHECKS),
    }


def test_live_readiness_gate_passes_only_head_bound_complete_evidence(tmp_path: Path) -> None:
    head_sha = "b" * 40
    _write_complete_evidence(tmp_path, head_sha=head_sha)

    result = live_readiness.evaluate_live_readiness(
        tmp_path,
        head_sha=head_sha,
        tested_sha=head_sha,
        ci_checks=_successful_ci_checks(),
    )

    assert result.ready
    assert result.tested_sha == head_sha
    assert dict(result.ci_checks) == _successful_ci_checks()
    assert not result.blockers
    assert set(result.passed_checks) == {
        "ci_has_no_account_order_or_secret_markers",
        "execution_costs",
        "five_bps_fee_configured",
        "five_bps_walk_forward",
        "forward_validation",
        "paper_execution",
        "risk_controls",
        "state_recovery",
        "tested_head_matches_source",
        *(f"ci_{name}" for name in live_readiness._REQUIRED_CI_CHECKS),
    }


def test_live_readiness_gate_rejects_failed_or_skipped_ci_checks(tmp_path: Path) -> None:
    head_sha = "b" * 40
    _write_complete_evidence(tmp_path, head_sha=head_sha)
    ci_checks = _successful_ci_checks()
    ci_checks["tests"] = "failure"
    ci_checks["portfolio_artifact"] = "skipped"

    result = live_readiness.evaluate_live_readiness(
        tmp_path,
        head_sha=head_sha,
        tested_sha=head_sha,
        ci_checks=ci_checks,
    )

    blockers = {blocker.code: blocker.detail for blocker in result.blockers}
    assert not result.ready
    assert blockers == {
        "ci_tests_failure": "required CI check tests concluded failure",
        "ci_portfolio_artifact_skipped": ("required CI check portfolio_artifact concluded skipped"),
    }
    assert dict(result.ci_checks) == ci_checks
    assert "ci_tests" not in result.passed_checks
    assert "ci_portfolio_artifact" not in result.passed_checks


def test_live_readiness_gate_fails_closed_without_ci_outcomes(tmp_path: Path) -> None:
    head_sha = "b" * 40
    _write_complete_evidence(tmp_path, head_sha=head_sha)

    result = live_readiness.evaluate_live_readiness(
        tmp_path,
        head_sha=head_sha,
        tested_sha=head_sha,
    )

    assert not result.ready
    assert dict(result.ci_checks) == {
        name: "missing" for name in live_readiness._REQUIRED_CI_CHECKS
    }
    assert {blocker.code for blocker in result.blockers} == {
        f"ci_{name}_missing" for name in live_readiness._REQUIRED_CI_CHECKS
    }


def test_live_readiness_gate_rejects_evidence_tested_on_different_sha(
    tmp_path: Path,
) -> None:
    head_sha = "b" * 40
    tested_sha = "e" * 40
    _write_complete_evidence(tmp_path, head_sha=head_sha)

    result = live_readiness.evaluate_live_readiness(
        tmp_path,
        head_sha=head_sha,
        tested_sha=tested_sha,
        ci_checks=_successful_ci_checks(),
    )

    blockers = {blocker.code: blocker.detail for blocker in result.blockers}
    assert not result.ready
    assert result.tested_sha == tested_sha
    assert blockers == {
        "tested_sha_mismatch": f"tested SHA {tested_sha} does not match source head {head_sha}"
    }
    assert "tested_head_matches_source" not in result.passed_checks


def test_live_readiness_api_requires_explicit_valid_revision_binding(
    tmp_path: Path,
) -> None:
    signature = inspect.signature(live_readiness.evaluate_live_readiness)
    assert signature.parameters["tested_sha"].default is inspect.Parameter.empty

    head_error = "head_sha must be a lowercase 40-character Git SHA"
    with pytest.raises(ValueError, match=head_error):
        live_readiness.evaluate_live_readiness(
            tmp_path,
            head_sha="not-a-git-revision",
            tested_sha="a" * 40,
            ci_checks=_successful_ci_checks(),
        )

    tested_error = "tested_sha must be a lowercase 40-character Git SHA"
    with pytest.raises(ValueError, match=tested_error):
        live_readiness.evaluate_live_readiness(
            tmp_path,
            head_sha="a" * 40,
            tested_sha="A" * 40,
            ci_checks=_successful_ci_checks(),
        )


def test_live_readiness_gate_rejects_indirect_secrets_and_checkout_credentials(
    tmp_path: Path,
) -> None:
    head_sha = "c" * 40
    _write_json(
        tmp_path / "config/okx_research.json",
        {"strategy": {"transaction_cost_bps": 5.0}},
    )
    workflow = tmp_path / ".github/workflows/live.yml"
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(
        """env:
  OKX_API_KEY: ${{ toJSON(SeCrEtS) }}
jobs:
  live:
    steps:
      - uses: actions/checkout@0123456789abcdef
      - run: curl /API/V5/TRADE/order
""",
        encoding="utf-8",
    )

    result = live_readiness.evaluate_live_readiness(
        tmp_path,
        head_sha=head_sha,
        tested_sha=head_sha,
        ci_checks=_successful_ci_checks(),
    )

    blockers = {blocker.code: blocker.detail for blocker in result.blockers}
    assert "workflow_account_or_secret_access" in blockers
    detail = blockers["workflow_account_or_secret_access"]
    assert "secret-context" in detail
    assert "credential-variable" in detail
    assert "trade-endpoint" in detail
    assert "checkout-credentials@line-6" in detail


def test_cli_writes_ci_outcomes_before_returning_failure(tmp_path: Path) -> None:
    _write_complete_evidence(tmp_path, head_sha="d" * 40)
    output_dir = tmp_path / "gate-output"
    ci_checks = _successful_ci_checks()
    ci_checks["walk_forward_verification"] = "failure"

    exit_code = live_readiness.main(
        [
            "--repo-root",
            str(tmp_path),
            "--head-sha",
            "d" * 40,
            "--tested-sha",
            "d" * 40,
            "--ci-status-json",
            json.dumps(ci_checks, sort_keys=True),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 1
    payload = json.loads((output_dir / "live_readiness.json").read_text(encoding="utf-8"))
    assert payload["ready"] is False
    assert payload["ci_checks"] == ci_checks
    assert any(
        blocker["code"] == "ci_walk_forward_verification_failure" for blocker in payload["blockers"]
    )
    markdown = (output_dir / "live_readiness.md").read_text(encoding="utf-8")
    assert "`walk_forward_verification`: `failure`" in markdown


def test_hourly_workflow_publishes_and_optionally_enforces_live_readiness() -> None:
    workflow_path = _REPOSITORY_ROOT / ".github/workflows/hourly-research.yml"
    workflow = workflow_path.read_text(encoding="utf-8")

    assert "enforce_live_readiness:" in workflow
    assert "default: false" in workflow
    assert "LIVE_READINESS_ARTIFACT_NAME" in workflow
    assert (
        "LIVE_READINESS_HEAD_SHA: ${{ github.event.pull_request.head.sha || github.sha }}"
        in workflow
    )
    assert "LIVE_READINESS_TESTED_SHA: ${{ github.sha }}" in workflow
    assert "Write live-readiness blocker summary" in workflow
    assert "Upload live-readiness blocker summary" in workflow
    assert "Enforce fail-closed live-readiness gate" in workflow
    assert workflow.count("PYTHONPATH=src python -m gpt_quant.live_readiness") == 2
    assert workflow.count('--head-sha "$LIVE_READINESS_HEAD_SHA"') == 2
    assert workflow.count('--tested-sha "$LIVE_READINESS_TESTED_SHA"') == 2
    assert workflow.count('--ci-status-json "$LIVE_READINESS_CI_STATUS_JSON"') == 2
    assert "steps.walk_forward_verification.outcome" in workflow
    assert "steps.portfolio_artifact.outcome" in workflow
    assert "--report-only" in workflow
    assert "!cancelled() && github.event_name == 'workflow_dispatch'" in workflow
    assert "retention-days: 30" in workflow
    assert "secrets." not in workflow
    assert "/api/v5/account" not in workflow
    assert "/api/v5/trade" not in workflow
