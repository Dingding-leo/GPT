from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_REQUIRED_EVIDENCE: dict[str, tuple[str, Mapping[str, Any]]] = {
    "five_bps_walk_forward": (
        "reports/live_readiness/five_bps_walk_forward.json",
        {
            "status": "pass",
            "fee_bps_one_way": 5.0,
            "selection_recomputed": True,
            "instruments": ["BTC-USDT", "ETH-USDT"],
        },
    ),
    "execution_costs": (
        "reports/live_readiness/execution_costs.json",
        {
            "status": "pass",
            "fee_bps_one_way": 5.0,
            "all_in_sensitivities_bps": [7.5, 10.0, 15.0],
            "separate_components": ["fee", "spread", "slippage", "impact", "latency"],
        },
    ),
    "paper_execution": (
        "reports/live_readiness/paper_execution.json",
        {
            "status": "pass",
            "paper_only": True,
            "account_connectivity_enabled": False,
            "replay_verified": True,
        },
    ),
    "state_recovery": (
        "reports/live_readiness/state_recovery.json",
        {
            "status": "pass",
            "restart_recovery_verified": True,
            "reconciliation_verified": True,
            "idempotency_verified": True,
        },
    ),
    "risk_controls": (
        "reports/live_readiness/risk_controls.json",
        {
            "status": "pass",
            "stale_data_kill_switch_verified": True,
            "loss_kill_switch_verified": True,
            "manual_stop_verified": True,
        },
    ),
    "forward_validation": (
        "reports/live_readiness/forward_validation.json",
        {
            "status": "pass",
            "untouched_market_verified": True,
            "prospective_forward_verified": True,
        },
    ),
}

_REQUIRED_CI_CHECKS = (
    "python_setup",
    "install",
    "lint_format",
    "tests",
    "walk_forward",
    "walk_forward_verification",
    "five_bps_evidence",
    "return_hashes",
    "source_artifact",
    "portfolio_risk",
    "portfolio_artifact",
)
_ALLOWED_CI_OUTCOMES = frozenset({"success", "failure", "cancelled", "skipped"})

_WORKFLOW_SECURITY_PATTERNS = (
    ("secret-context", r"\$\{\{[^}]*\bsecrets\b"),
    (
        "credential-variable",
        r"(?m)^\s*[A-Z0-9_-]*(?:API[_-]?KEY|SECRET(?:[_-]?KEY)?|PASSPHRASE|ACCESS[_-]?TOKEN)\s*:",
    ),
    ("account-endpoint", r"/api/v5/account(?:/|\b)"),
    ("trade-endpoint", r"/api/v5/trade(?:/|\b)"),
    ("order-call", r"\b(?:place|submit|send|create)_order\s*\("),
)
_GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")


@dataclass(frozen=True, slots=True)
class LiveReadinessBlocker:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class LiveReadinessResult:
    head_sha: str
    tested_sha: str
    ci_checks: tuple[tuple[str, str], ...]
    ready: bool
    passed_checks: tuple[str, ...]
    blockers: tuple[LiveReadinessBlocker, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "blockers": [asdict(blocker) for blocker in self.blockers],
            "ci_checks": dict(self.ci_checks),
            "head_sha": self.head_sha,
            "passed_checks": list(self.passed_checks),
            "ready": self.ready,
            "tested_sha": self.tested_sha,
        }


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read valid JSON object from {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _matches_expected(actual: object, expected: object) -> bool:
    if isinstance(expected, list):
        return isinstance(actual, list) and actual == expected
    return actual == expected


def _validated_revision(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or _GIT_SHA_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase 40-character Git SHA")
    return value


def _validated_ci_checks(ci_checks: Mapping[str, str] | None) -> tuple[tuple[str, str], ...]:
    if ci_checks is None:
        return tuple((name, "missing") for name in _REQUIRED_CI_CHECKS)
    unexpected = sorted(set(ci_checks) - set(_REQUIRED_CI_CHECKS))
    if unexpected:
        raise ValueError(f"unexpected CI checks: {', '.join(unexpected)}")
    validated: list[tuple[str, str]] = []
    for name in _REQUIRED_CI_CHECKS:
        outcome = ci_checks.get(name, "missing")
        if not isinstance(outcome, str) or outcome not in _ALLOWED_CI_OUTCOMES:
            allowed = ", ".join(sorted(_ALLOWED_CI_OUTCOMES))
            raise ValueError(f"CI check {name} must be one of: {allowed}")
        validated.append((name, outcome))
    return tuple(validated)


def _validate_evidence(
    repo_root: Path,
    *,
    name: str,
    relative_path: str,
    expected: Mapping[str, Any],
    head_sha: str,
    tested_sha: str,
) -> LiveReadinessBlocker | None:
    path = repo_root / relative_path
    if path.is_symlink() or not path.is_file():
        return LiveReadinessBlocker(
            code=f"missing_{name}",
            detail=f"required evidence is missing or not a regular file: {relative_path}",
        )
    try:
        payload = _load_json_object(path)
    except ValueError as exc:
        return LiveReadinessBlocker(code=f"invalid_{name}", detail=str(exc))
    if payload.get("head_sha") != head_sha:
        return LiveReadinessBlocker(
            code=f"stale_{name}",
            detail=f"{relative_path} is not bound to head {head_sha}",
        )
    if payload.get("tested_sha") != tested_sha:
        return LiveReadinessBlocker(
            code=f"stale_{name}",
            detail=f"{relative_path} is not bound to tested revision {tested_sha}",
        )
    mismatches = [
        key
        for key, expected_value in expected.items()
        if not _matches_expected(payload.get(key), expected_value)
    ]
    if mismatches:
        return LiveReadinessBlocker(
            code=f"failed_{name}",
            detail=f"{relative_path} does not satisfy fields: {', '.join(mismatches)}",
        )
    return None


def _checkout_credential_findings(workflow: str) -> list[str]:
    lines = workflow.splitlines()
    findings: list[str] = []
    for index, line in enumerate(lines):
        if not re.search(r"\buses:\s*actions/checkout@", line, re.IGNORECASE):
            continue
        indentation = len(line) - len(line.lstrip())
        block: list[str] = []
        for later in lines[index + 1 :]:
            if later.strip() and len(later) - len(later.lstrip()) < indentation:
                break
            block.append(later)
        if not any(
            re.search(
                r"^\s*persist-credentials:\s*false\s*(?:#.*)?$",
                candidate,
                re.IGNORECASE,
            )
            for candidate in block
        ):
            findings.append(f"checkout-credentials@line-{index + 1}")
    return findings


def _unsafe_workflow_findings(workflow: str) -> list[str]:
    findings = [
        label
        for label, pattern in _WORKFLOW_SECURITY_PATTERNS
        if re.search(pattern, workflow, re.IGNORECASE)
    ]
    findings.extend(_checkout_credential_findings(workflow))
    return findings


def evaluate_live_readiness(
    repo_root: str | Path,
    *,
    head_sha: str,
    tested_sha: str,
    ci_checks: Mapping[str, str] | None = None,
) -> LiveReadinessResult:
    root = Path(repo_root).resolve()
    source_head_sha = _validated_revision(head_sha, field_name="head_sha")
    tested_revision_sha = _validated_revision(tested_sha, field_name="tested_sha")
    validated_ci_checks = _validated_ci_checks(ci_checks)
    blockers: list[LiveReadinessBlocker] = []
    passed: list[str] = []

    for name, outcome in validated_ci_checks:
        if outcome == "success":
            passed.append(f"ci_{name}")
        else:
            blockers.append(
                LiveReadinessBlocker(
                    code=f"ci_{name}_{outcome}",
                    detail=f"required CI check {name} concluded {outcome}",
                )
            )

    if tested_revision_sha == source_head_sha:
        passed.append("tested_head_matches_source")
    else:
        mismatch_detail = f"tested SHA {tested_revision_sha} does not match source head"
        mismatch_detail += f" {source_head_sha}"
        blockers.append(
            LiveReadinessBlocker(
                code="tested_sha_mismatch",
                detail=mismatch_detail,
            )
        )

    config_path = root / "config/okx_research.json"
    try:
        config = _load_json_object(config_path)
        strategy = config.get("strategy")
        fee = strategy.get("transaction_cost_bps") if isinstance(strategy, Mapping) else None
        if fee == 5.0:
            passed.append("five_bps_fee_configured")
        else:
            blockers.append(
                LiveReadinessBlocker(
                    code="fee_baseline_not_5bps",
                    detail="config/okx_research.json must declare 5.0 one-way fee bps",
                )
            )
    except ValueError as exc:
        blockers.append(LiveReadinessBlocker(code="invalid_research_config", detail=str(exc)))

    workflow_dir = root / ".github/workflows"
    workflow_files = sorted((*workflow_dir.glob("*.yml"), *workflow_dir.glob("*.yaml")))
    unsafe_markers: list[str] = []
    for workflow_path in workflow_files:
        workflow = workflow_path.read_text(encoding="utf-8")
        unsafe_markers.extend(
            f"{workflow_path.relative_to(root)}:{finding}"
            for finding in _unsafe_workflow_findings(workflow)
        )
    if unsafe_markers:
        blockers.append(
            LiveReadinessBlocker(
                code="workflow_account_or_secret_access",
                detail="forbidden workflow capabilities: " + ", ".join(unsafe_markers),
            )
        )
    else:
        passed.append("ci_has_no_account_order_or_secret_markers")

    for name, (relative_path, expected) in _REQUIRED_EVIDENCE.items():
        blocker = _validate_evidence(
            root,
            name=name,
            relative_path=relative_path,
            expected=expected,
            head_sha=source_head_sha,
            tested_sha=tested_revision_sha,
        )
        if blocker is None:
            passed.append(name)
        else:
            blockers.append(blocker)

    return LiveReadinessResult(
        head_sha=source_head_sha,
        tested_sha=tested_revision_sha,
        ci_checks=validated_ci_checks,
        ready=not blockers,
        passed_checks=tuple(sorted(passed)),
        blockers=tuple(blockers),
    )


def _markdown_report(result: LiveReadinessResult) -> str:
    lines = [
        "# Live Readiness Gate",
        "",
        f"- Source head SHA: `{result.head_sha}`",
        f"- Tested SHA: `{result.tested_sha}`",
        f"- Ready: `{str(result.ready).lower()}`",
        "",
        "## CI checks",
        "",
    ]
    lines.extend(f"- `{name}`: `{outcome}`" for name, outcome in result.ci_checks)
    lines.extend(["", "## Passed checks", ""])
    lines.extend(f"- `{name}`" for name in result.passed_checks)
    if not result.passed_checks:
        lines.append("- None")
    lines.extend(["", "## Launch blockers", ""])
    lines.extend(f"- `{blocker.code}`: {blocker.detail}" for blocker in result.blockers)
    if not result.blockers:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def write_live_readiness_report(
    result: LiveReadinessResult,
    output_dir: str | Path,
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = {
        "json": output / "live_readiness.json",
        "markdown": output / "live_readiness.md",
    }
    paths["json"].write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    paths["markdown"].write_text(_markdown_report(result), encoding="utf-8")
    return paths


def _ci_status_json(value: str) -> dict[str, str]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError("--ci-status-json must contain valid JSON") from exc
    if not isinstance(payload, dict) or not all(
        isinstance(key, str) and isinstance(outcome, str) for key, outcome in payload.items()
    ):
        raise argparse.ArgumentTypeError("--ci-status-json must contain a string-to-string object")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate fail-closed paper/live readiness")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--tested-sha", required=True)
    parser.add_argument("--ci-status-json", required=True, type=_ci_status_json)
    parser.add_argument("--output-dir", default="reports/live-readiness-gate")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="write the blocker report without returning a failing process status",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = evaluate_live_readiness(
        args.repo_root,
        head_sha=args.head_sha,
        tested_sha=args.tested_sha,
        ci_checks=args.ci_status_json,
    )
    write_live_readiness_report(result, args.output_dir)
    return 0 if result.ready or args.report_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
