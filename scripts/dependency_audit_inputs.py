from __future__ import annotations

import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path
from urllib.parse import urlparse

_DISTRIBUTION_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
_REQUIREMENT_NAME = re.compile(
    r"^(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)(?=$|[\s\[()<>=!~;])"
)
_EXTRA_NAME = _DISTRIBUTION_NAME
_EXTRA_SEPARATOR = re.compile(r"[-_.]+")
_MARKER_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
_SHA256_HEX = re.compile(r"^[0-9A-Fa-f]{64}$")
_ALLOWED_MARKER_VARIABLES = frozenset({"python_version"})
_MARKER_KEYWORDS = frozenset({"and", "in", "not", "or"})
_REQUIRED_PYTHON = ">=3.11,<3.15"
_REQUIRED_BUILD_BACKEND = "setuptools.build_meta"
_PYPI_FILE_HOST = "files.pythonhosted.org"
_FORBIDDEN_LEGACY_BUILD_FILES = frozenset({"setup.py", "setup.cfg"})


def _canonical_distribution_name(name: str) -> str:
    return _EXTRA_SEPARATOR.sub("-", name).lower()


def _canonical_extra_name(name: str) -> str:
    return _canonical_distribution_name(name)


def _validated_project_name(value: object) -> tuple[str, str]:
    if not isinstance(value, str) or _DISTRIBUTION_NAME.fullmatch(value) is None:
        raise ValueError("[project].name must be a valid non-empty distribution name")
    return value, _canonical_distribution_name(value)


def _canonical_requirement_name(requirement: str, *, label: str) -> str:
    base = requirement.partition(";")[0].strip()
    match = _REQUIREMENT_NAME.match(base)
    if match is None:
        raise ValueError(f"unable to parse package name from {label} requirement: {requirement!r}")
    return _canonical_distribution_name(match.group("name"))


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


def _validate_environment_marker(requirement: str, *, label: str) -> None:
    _, separator, raw_marker = requirement.partition(";")
    if not separator:
        return

    marker = raw_marker.strip()
    if not marker:
        raise ValueError(f"empty environment marker in {label} requirement: {requirement!r}")
    identifiers = {
        identifier
        for identifier in _MARKER_IDENTIFIER.findall(_unquoted_marker_text(marker))
        if identifier not in _MARKER_KEYWORDS
    }
    if identifiers != _ALLOWED_MARKER_VARIABLES:
        raise ValueError(
            f"environment markers in {label} may reference only 'python_version'; "
            f"found {sorted(identifiers)!r} in {requirement!r}"
        )


def _validated_requirements(
    value: object,
    *,
    label: str,
    canonical_project_name: str,
    require_non_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (require_non_empty and not value):
        expectation = "a non-empty list" if require_non_empty else "a list"
        raise ValueError(f"{label} must be {expectation}")

    validated: list[str] = []
    for raw_requirement in value:
        if not isinstance(raw_requirement, str):
            raise ValueError(f"every {label} requirement must be a string")
        requirement = raw_requirement.strip()
        if _unsafe_requirement(requirement):
            raise ValueError(f"unsafe {label} requirement: {raw_requirement!r}")
        _validate_environment_marker(requirement, label=label)
        requirement_name = _canonical_requirement_name(requirement, label=label)
        if requirement_name == canonical_project_name:
            raise ValueError(f"{label} must not reference the project itself: {raw_requirement!r}")
        validated.append(requirement)
    return validated


def _unique_sorted(requirements: list[str]) -> list[str]:
    return sorted(set(requirements), key=lambda value: value.casefold())


def validate_legacy_build_file_statuses(status_path: Path) -> dict[str, int]:
    statuses = json.loads(status_path.read_text(encoding="utf-8"))
    if not isinstance(statuses, dict) or set(statuses) != _FORBIDDEN_LEGACY_BUILD_FILES:
        raise ValueError(
            "legacy build file status manifest must contain exactly "
            f"{sorted(_FORBIDDEN_LEGACY_BUILD_FILES)!r}"
        )

    validated: dict[str, int] = {}
    for path in sorted(_FORBIDDEN_LEGACY_BUILD_FILES):
        status = statuses[path]
        if isinstance(status, bool) or not isinstance(status, int):
            raise ValueError(f"HTTP status for {path} must be an integer")
        if status == 200:
            raise ValueError(f"legacy setuptools file is not allowed: {path}")
        if status != 404:
            raise ValueError(
                f"unable to verify absence of legacy setuptools file {path}: HTTP {status}"
            )
        validated[path] = status
    return validated


def prepare_audit_inputs(pyproject_path: Path, output_dir: Path) -> dict[str, object]:
    source_bytes = pyproject_path.read_bytes()
    pyproject = tomllib.loads(source_bytes.decode("utf-8"))

    build_system = pyproject.get("build-system")
    if not isinstance(build_system, dict):
        raise ValueError("pyproject.toml must define [build-system]")
    build_backend = build_system.get("build-backend")
    if build_backend != _REQUIRED_BUILD_BACKEND:
        raise ValueError(
            f"[build-system].build-backend must be exactly {_REQUIRED_BUILD_BACKEND!r}"
        )
    if "backend-path" in build_system:
        raise ValueError("[build-system].backend-path is not allowed")

    project = pyproject.get("project")
    if not isinstance(project, dict):
        raise ValueError("pyproject.toml must define [project]")
    project_name, canonical_project_name = _validated_project_name(project.get("name"))
    if project.get("requires-python") != _REQUIRED_PYTHON:
        raise ValueError(f"[project].requires-python must be exactly {_REQUIRED_PYTHON!r}")

    build_requirements = _validated_requirements(
        build_system.get("requires"),
        label="[build-system].requires",
        canonical_project_name=canonical_project_name,
        require_non_empty=True,
    )

    dynamic = project.get("dynamic", [])
    if not isinstance(dynamic, list) or not all(isinstance(value, str) for value in dynamic):
        raise ValueError("[project].dynamic must be a list of strings")
    if dynamic:
        raise ValueError("dynamic project metadata is not allowed")
    tool = pyproject.get("tool", {})
    if not isinstance(tool, dict):
        raise ValueError("[tool] must be a table")
    setuptools_config = tool.get("setuptools", {})
    if not isinstance(setuptools_config, dict):
        raise ValueError("[tool.setuptools] must be a table")
    if "dynamic" in setuptools_config:
        raise ValueError("[tool.setuptools.dynamic] is not allowed")
    if "cmdclass" in setuptools_config:
        raise ValueError("[tool.setuptools.cmdclass] is not allowed")

    project_requirements = _validated_requirements(
        project.get("dependencies", []),
        label="[project].dependencies",
        canonical_project_name=canonical_project_name,
    )
    optional_dependencies = project.get("optional-dependencies", {})
    if not isinstance(optional_dependencies, dict):
        raise ValueError("[project.optional-dependencies] must be a table")

    canonical_names: dict[str, str] = {}
    extra_names: list[str] = []
    for name, value in optional_dependencies.items():
        if not isinstance(name, str) or _EXTRA_NAME.fullmatch(name) is None:
            raise ValueError(f"invalid optional-dependency extra name: {name!r}")
        canonical_name = _canonical_extra_name(name)
        conflicting_name = canonical_names.get(canonical_name)
        if conflicting_name is not None:
            raise ValueError(
                "optional-dependency extra names normalize to the same value: "
                f"{conflicting_name!r} and {name!r}"
            )
        canonical_names[canonical_name] = name
        extra_names.append(name)
        project_requirements.extend(
            _validated_requirements(
                value,
                label=f"[project.optional-dependencies].{name}",
                canonical_project_name=canonical_project_name,
            )
        )

    build_requirements = _unique_sorted(build_requirements)
    project_requirements = _unique_sorted(project_requirements)
    if not project_requirements:
        raise ValueError("project and optional dependencies cannot both be empty")

    manifest = {
        "schema_version": 1,
        "source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "project_name": project_name,
        "canonical_project_name": canonical_project_name,
        "requires_python": _REQUIRED_PYTHON,
        "build_backend": _REQUIRED_BUILD_BACKEND,
        "build_requirements": build_requirements,
        "project_requirements": project_requirements,
        "optional_extras": sorted(extra_names, key=_canonical_extra_name),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "build-requirements.in").write_text(
        "\n".join(build_requirements) + "\n",
        encoding="utf-8",
    )
    (output_dir / "project-requirements.in").write_text(
        "\n".join(project_requirements) + "\n",
        encoding="utf-8",
    )
    (output_dir / "dependency-inputs.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def lock_resolution_report(
    report_path: Path,
    requirements_path: Path,
    evidence_path: Path,
) -> list[str]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    install = report.get("install")
    if not isinstance(install, list) or not install:
        raise ValueError("pip resolution report must contain at least one installation")

    resolved: dict[str, dict[str, str]] = {}
    for item in install:
        if not isinstance(item, dict) or item.get("is_direct") is not False:
            raise ValueError("pip resolution contains a direct or malformed requirement")
        metadata = item.get("metadata")
        download_info = item.get("download_info")
        if not isinstance(metadata, dict) or not isinstance(download_info, dict):
            raise ValueError("pip resolution omitted metadata or download information")

        name = metadata.get("name")
        version = metadata.get("version")
        url = download_info.get("url")
        archive_info = download_info.get("archive_info")
        if not all(isinstance(value, str) and value for value in (name, version, url)):
            raise ValueError("pip resolution omitted package name, version, or URL")
        parsed_url = urlparse(url)
        if parsed_url.scheme != "https" or parsed_url.hostname != _PYPI_FILE_HOST:
            raise ValueError(f"resolved artifact is not from public PyPI: {url!r}")
        if not isinstance(archive_info, dict):
            raise ValueError("pip resolution omitted archive information")
        hashes = archive_info.get("hashes")
        sha256 = hashes.get("sha256") if isinstance(hashes, dict) else None
        if not isinstance(sha256, str) or _SHA256_HEX.fullmatch(sha256) is None:
            raise ValueError("pip resolution omitted a valid artifact SHA-256")
        sha256 = sha256.lower()

        canonical_name = _EXTRA_SEPARATOR.sub("-", name).lower()
        existing = resolved.get(canonical_name)
        record = {"name": name, "version": version, "url": url, "sha256": sha256}
        if existing is not None and existing != record:
            raise ValueError(f"conflicting resolved artifacts for {name}")
        resolved[canonical_name] = record

    ordered_records = [resolved[name] for name in sorted(resolved)]
    pinned = [f"{record['name']}=={record['version']}" for record in ordered_records]
    requirements_path.write_text("\n".join(pinned) + "\n", encoding="utf-8")
    evidence_path.write_text(
        json.dumps(ordered_records, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return pinned


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        if len(arguments) == 3 and arguments[0] == "prepare":
            prepare_audit_inputs(Path(arguments[1]), Path(arguments[2]))
        elif len(arguments) == 2 and arguments[0] == "validate-legacy-build-files":
            validate_legacy_build_file_statuses(Path(arguments[1]))
        elif len(arguments) == 4 and arguments[0] == "lock-report":
            lock_resolution_report(
                Path(arguments[1]),
                Path(arguments[2]),
                Path(arguments[3]),
            )
        else:
            print(
                "usage: dependency_audit_inputs.py prepare PYPROJECT OUTPUT_DIR | "
                "validate-legacy-build-files STATUS_JSON | "
                "lock-report REPORT REQUIREMENTS EVIDENCE",
                file=sys.stderr,
            )
            return 2
    except (
        OSError,
        UnicodeDecodeError,
        tomllib.TOMLDecodeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        print(f"dependency audit input error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
