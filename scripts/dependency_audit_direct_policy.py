from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from dependency_audit_inputs import _canonical_requirement_name, prepare_audit_inputs

_APPROVED_DIRECT_DEPENDENCIES = {
    "build": frozenset({"setuptools"}),
    "project": frozenset({"numpy", "pandas", "pytest", "ruff"}),
}


def _canonical_names(requirements: object, *, label: str) -> list[str]:
    if not isinstance(requirements, list) or not all(
        isinstance(requirement, str) for requirement in requirements
    ):
        raise ValueError(f"validated {label} requirements must be a list of strings")
    return sorted(
        {
            _canonical_requirement_name(requirement, label=label)
            for requirement in requirements
        }
    )


def enforce_direct_dependency_policy(
    pyproject_path: Path,
    evidence_path: Path,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="dependency-direct-policy-") as temporary_dir:
        manifest = prepare_audit_inputs(pyproject_path, Path(temporary_dir))

    declared = {
        "build": _canonical_names(
            manifest.get("build_requirements"),
            label="[build-system].requires",
        ),
        "project": _canonical_names(
            manifest.get("project_requirements"),
            label="project and optional dependencies",
        ),
    }
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
        "schema_version": 1,
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
