from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_MARKER_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")
_NONEMPTY_EXTRA_EQUALITY = re.compile(
    r"""\bextra\s*==\s*(?:"[^"]+"|'[^']+')""",
    re.IGNORECASE,
)
_MARKER_KEYWORDS = frozenset({"and", "in", "not", "or"})
_ALLOWED_MARKER_VARIABLES = frozenset({"python_version"})
_REQUIREMENT_LISTS = ("build_requirements", "project_requirements")
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")


def _unquoted_marker_text(marker: str) -> str:
    unquoted: list[str] = []
    quote: str | None = None
    escaped = False
    for character in marker:
        if quote is None:
            if character in {"'", '"'}:
                quote = character
                unquoted.append(" ")
            else:
                unquoted.append(character)
            continue

        unquoted.append(" ")
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == quote:
            quote = None

    if quote is not None:
        raise ValueError("environment marker contains an unterminated quoted string")
    return "".join(unquoted)


def _marker_identifiers(marker: str) -> set[str]:
    return {
        identifier
        for identifier in _MARKER_IDENTIFIER.findall(_unquoted_marker_text(marker))
        if identifier not in _MARKER_KEYWORDS
    }


def _safe_inactive_extra_marker(marker: str, identifiers: set[str]) -> bool:
    unquoted = _unquoted_marker_text(marker).lower()
    tokens = set(_MARKER_IDENTIFIER.findall(unquoted))
    return (
        "extra" in identifiers
        and "or" not in tokens
        and "not" not in tokens
        and _NONEMPTY_EXTRA_EQUALITY.search(marker) is not None
    )


def _requirement_requests_extra(requirement: str) -> bool:
    base = requirement.partition(";")[0]
    return "[" in base or "]" in base


def _unsafe_requirement(requirement: str) -> bool:
    lowered = requirement.lower()
    return (
        not requirement
        or "\n" in requirement
        or "\r" in requirement
        or requirement.startswith(("-", ".", "/", "\\", "~"))
        or _WINDOWS_PATH.match(requirement) is not None
        or "@" in requirement
        or "://" in requirement
        or lowered.startswith(("file:", "git+", "hg+", "svn+", "bzr+"))
    )


def _canonical_requirement_name(requirement: str) -> str:
    match = _REQUIREMENT_NAME.match(requirement)
    if match is None:
        raise ValueError(f"unable to parse dependency name from {requirement!r}")
    return re.sub(r"[-_.]+", "-", match.group(0)).lower()


def validate_input_manifest(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for field in _REQUIREMENT_LISTS:
        requirements = manifest.get(field)
        if not isinstance(requirements, list) or not all(
            isinstance(requirement, str) for requirement in requirements
        ):
            raise ValueError(f"dependency input manifest {field} must be a list of strings")
        for requirement in requirements:
            if _requirement_requests_extra(requirement):
                raise ValueError(
                    "third-party dependency extras are not allowed because transitive "
                    f"extra markers cannot be audited cross-platform: {requirement!r}"
                )


def _resolution_install(report_path: Path) -> list[dict[str, object]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    install = report.get("install")
    if not isinstance(install, list) or not install:
        raise ValueError("pip resolution report must contain at least one installation")
    if not all(isinstance(item, dict) for item in install):
        raise ValueError("pip resolution report contains a malformed installation")
    return install


def _platform_requirements(report_path: Path) -> list[str]:
    requirements: set[str] = set()
    for item in _resolution_install(report_path):
        metadata = item.get("metadata")
        if not isinstance(metadata, dict):
            raise ValueError("pip resolution omitted package metadata")
        requires_dist = metadata.get("requires_dist", [])
        if requires_dist is None:
            requires_dist = []
        if not isinstance(requires_dist, list) or not all(
            isinstance(requirement, str) for requirement in requires_dist
        ):
            raise ValueError("resolved package metadata has malformed Requires-Dist entries")

        for raw_requirement in requires_dist:
            requirement = raw_requirement.strip()
            if _unsafe_requirement(requirement):
                raise ValueError(f"unsafe transitive dependency requirement: {raw_requirement!r}")
            base, separator, raw_marker = requirement.partition(";")
            base = base.strip()
            if not base:
                raise ValueError(
                    f"transitive dependency requirement has no package: {requirement!r}"
                )
            _canonical_requirement_name(base)

            if not separator:
                if _requirement_requests_extra(base):
                    raise ValueError(
                        "transitive dependency extras are not allowed because their marker "
                        f"closure is not independently auditable: {requirement!r}"
                    )
                continue

            marker = raw_marker.strip()
            if not marker:
                raise ValueError(f"empty transitive environment marker: {requirement!r}")
            identifiers = _marker_identifiers(marker)
            if _safe_inactive_extra_marker(marker, identifiers):
                continue
            if _requirement_requests_extra(base):
                raise ValueError(
                    "active or ambiguous transitive dependency extras are not allowed: "
                    f"{requirement!r}"
                )
            if identifiers != _ALLOWED_MARKER_VARIABLES:
                requirements.add(base)

    return sorted(requirements, key=lambda value: value.casefold())


def collect_platform_requirements(report_path: Path, output_path: Path) -> list[str]:
    requirements = _platform_requirements(report_path)
    output_path.write_text(
        "".join(f"{requirement}\n" for requirement in requirements),
        encoding="utf-8",
    )
    return requirements


def verify_platform_closure(report_path: Path, expected_path: Path) -> None:
    expected = [
        line.strip()
        for line in expected_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    actual = _platform_requirements(report_path)
    if actual != expected:
        raise ValueError(
            "transitive platform dependency closure changed after promotion: "
            f"expected {expected!r}, found {actual!r}"
        )


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) == 2 and arguments[0] == "validate-manifest":
            validate_input_manifest(Path(arguments[1]))
        elif len(arguments) == 3 and arguments[0] == "collect":
            collect_platform_requirements(Path(arguments[1]), Path(arguments[2]))
        elif len(arguments) == 3 and arguments[0] == "verify":
            verify_platform_closure(Path(arguments[1]), Path(arguments[2]))
        else:
            print(
                "usage: dependency_audit_transitive.py validate-manifest MANIFEST | "
                "collect REPORT OUTPUT | verify REPORT EXPECTED",
                file=sys.stderr,
            )
            return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"transitive dependency audit error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
