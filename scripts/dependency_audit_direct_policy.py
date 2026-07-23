from __future__ import annotations

import json
import sys
import tempfile
import tomllib
from pathlib import Path

from dependency_audit_inputs import (
    _canonical_extra_name,
    _canonical_requirement_name,
    prepare_audit_inputs,
)

_APPROVED_DIRECT_DEPENDENCIES = {
    "build": frozenset({"setuptools"}),
    "runtime": frozenset({"numpy", "pandas"}),
    "optional:dev": frozenset({"pytest", "ruff"}),
}


def _reject_requested_extras(requirement: str, *, label: str) -> None:
    requirement_without_marker = requirement.partition(";")[0]
    if "[" in requirement_without_marker or "]" in requirement_without_marker:
        raise ValueError(
            f"requested dependency extras are not allowed in {label}: {requirement!r}; "
            "approve the resulting direct dependencies explicitly instead"
        )


def _canonical_names(requirements: object, *, label: str) -> list[str]:
    if not isinstance(requirements, list) or not all(
        isinstance(requirement, str) for requirement in requirements
    ):
        raise ValueError(f"validated {label} requirements must be a list of strings")

    canonical_names = []
    for requirement in requirements:
        _reject_requested_extras(requirement, label=label)
        canonical_names.append(_canonical_requirement_name(requirement, label=label))

    counts: dict[str, int] = {}
    for name in canonical_names:
        counts[name] = counts.get(name, 0) + 1
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(
            f"{label} must declare each canonical dependency name at most once: {duplicates!r}"
        )
    return sorted(canonical_names)


def _declared_direct_dependencies(pyproject_path: Path) -> dict[str, list[str]]:
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    build_system = pyproject["build-system"]
    project = pyproject["project"]
    optional_dependencies = project.get("optional-dependencies", {})

    declared = {
        "build": _canonical_names(
            build_system["requires"],
            label="[build-system].requires",
        ),
        "runtime": _canonical_names(
            project.get("dependencies", []),
            label="[project].dependencies",
        ),
    }
    for extra_name, requirements in optional_dependencies.items():
        scope = f"optional:{_canonical_extra_name(extra_name)}"
        declared[scope] = _canonical_names(
            requirements,
            label=f"[project.optional-dependencies].{extra_name}",
        )
    return dict(sorted(declared.items()))


def _reject_cross_scope_duplicates(declared: dict[str, list[str]]) -> None:
    scopes_by_name: dict[str, list[str]] = {}
    for scope, names in declared.items():
        for name in names:
            scopes_by_name.setdefault(name, []).append(scope)
    duplicates = {
        name: sorted(scopes) for name, scopes in scopes_by_name.items() if len(scopes) > 1
    }
    if duplicates:
        raise ValueError(
            "direct dependency names must not be repeated across declaration scopes: "
            f"{duplicates!r}"
        )


def enforce_direct_dependency_policy(
    pyproject_path: Path,
    evidence_path: Path,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="dependency-direct-policy-") as temporary_dir:
        prepare_audit_inputs(pyproject_path, Path(temporary_dir))

    declared = _declared_direct_dependencies(pyproject_path)
    _reject_cross_scope_duplicates(declared)

    unapproved_scopes = sorted(set(declared) - set(_APPROVED_DIRECT_DEPENDENCIES))
    if unapproved_scopes:
        raise ValueError(
            "unapproved direct dependency declaration scopes are not allowed: "
            f"{unapproved_scopes!r}; approve scopes in trusted base policy before declaring them"
        )

    unapproved = {
        scope: sorted(set(names) - _APPROVED_DIRECT_DEPENDENCIES[scope])
        for scope, names in declared.items()
        if set(names) - _APPROVED_DIRECT_DEPENDENCIES[scope]
    }
    if unapproved:
        raise ValueError(
            "unapproved direct dependency names are not allowed in their declared scopes: "
            f"{unapproved!r}; approve names in trusted base policy before declaring them"
        )

    evidence: dict[str, object] = {
        "schema_version": 2,
        "approved_direct_dependencies": {
            scope: sorted(names) for scope, names in _APPROVED_DIRECT_DEPENDENCIES.items()
        },
        "declared_direct_dependencies": declared,
    }
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return evidence


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        print(
            "usage: dependency_audit_direct_policy.py PYPROJECT EVIDENCE_JSON",
            file=sys.stderr,
        )
        return 2

    try:
        enforce_direct_dependency_policy(Path(arguments[0]), Path(arguments[1]))
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"dependency direct-policy validation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
