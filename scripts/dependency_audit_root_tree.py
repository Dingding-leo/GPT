from __future__ import annotations

import json
import sys
from pathlib import Path

_FORBIDDEN_ROOT_NAMES = frozenset({"setup.py", "setup.cfg"})
_GITHUB_CONTENTS_DIRECTORY_LIMIT = 1000


def validate_root_contents(contents_path: Path) -> tuple[str, ...]:
    contents = json.loads(contents_path.read_text(encoding="utf-8"))
    if not isinstance(contents, list):
        raise ValueError("proposed root contents must be a JSON list")
    if len(contents) >= _GITHUB_CONTENTS_DIRECTORY_LIMIT:
        raise ValueError("proposed root contents reached the GitHub API directory limit")

    names: list[str] = []
    for index, entry in enumerate(contents):
        if not isinstance(entry, dict):
            raise ValueError(f"proposed root entry {index} must be an object")
        name = entry.get("name")
        path = entry.get("path")
        entry_type = entry.get("type")
        if not isinstance(name, str) or not name:
            raise ValueError(f"proposed root entry {index} must contain a non-empty name")
        if not isinstance(path, str) or path != name:
            raise ValueError(f"proposed root entry {index} must describe an exact root path")
        if not isinstance(entry_type, str) or not entry_type:
            raise ValueError(f"proposed root entry {index} must contain a type")
        if name.casefold() in _FORBIDDEN_ROOT_NAMES:
            raise ValueError(f"legacy setuptools file is not allowed: {name}")
        names.append(name)
    return tuple(names)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 1:
        print("usage: dependency_audit_root_tree.py ROOT_CONTENTS_JSON", file=sys.stderr)
        return 2
    try:
        validate_root_contents(Path(arguments[0]))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"dependency audit root-tree error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
