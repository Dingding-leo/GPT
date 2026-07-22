from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github/workflows/dependency-review.yml"


def test_dependency_resolution_promotes_and_verifies_platform_markers() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    validate = workflow.index("dependency_audit_transitive.py validate-manifest")
    initial = workflow.index("${dependency_set}-initial-resolution.json")
    collect = workflow.index("dependency_audit_transitive.py collect")
    final = workflow.index("${dependency_set}-resolution.json")
    verify = workflow.index("dependency_audit_transitive.py verify")
    lock = workflow.index("dependency_audit_inputs.py lock-report")

    assert validate < initial < collect < final < verify < lock
    assert '--requirement "reports/security/${dependency_set}-platform-requirements.in"' in workflow
    assert workflow.count("dependency_audit_transitive.py collect") == 1
    assert workflow.count("dependency_audit_transitive.py verify") == 1
