from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path, PurePosixPath
from typing import Final

_DEFAULT_OUTPUT_NAME: Final = "artifact-manifest.sha256"
_CHUNK_SIZE: Final = 1024 * 1024


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_output_name(output_name: str) -> str:
    if not output_name or Path(output_name).name != output_name or output_name in {".", ".."}:
        raise ValueError("output name must be one plain file name")
    if any(character in output_name for character in ("\n", "\r", "\\")):
        raise ValueError("output name contains unsupported manifest characters")
    return output_name


def _manifest_files(root: Path, output_name: str, temporary_name: str) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"artifact tree must not contain symlinks: {path}")
        if not path.is_file() or path.name in {output_name, temporary_name}:
            continue
        relative = path.relative_to(root).as_posix()
        if any(character in relative for character in ("\n", "\r", "\\")):
            raise ValueError(f"artifact path contains unsupported manifest characters: {relative}")
        files.append(path)
    return sorted(files, key=lambda path: path.relative_to(root).as_posix())


def verify_manifest(root: str | Path, output_name: str = _DEFAULT_OUTPUT_NAME) -> None:
    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise ValueError("artifact root must be a directory")
    output_name = _validated_output_name(output_name)
    manifest_path = root_path / output_name
    try:
        lines = manifest_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ValueError(f"artifact manifest is missing: {manifest_path}") from exc
    if not lines:
        raise ValueError("artifact manifest must contain at least one file")

    seen: set[str] = set()
    previous_relative: str | None = None
    for line in lines:
        expected, separator, relative = line.partition("  ")
        if separator != "  " or len(expected) != 64:
            raise ValueError("artifact manifest contains a malformed entry")
        try:
            int(expected, 16)
        except ValueError as exc:
            raise ValueError("artifact manifest contains a non-hexadecimal digest") from exc
        pure_relative = PurePosixPath(relative)
        if pure_relative.is_absolute() or not relative or ".." in pure_relative.parts:
            raise ValueError("artifact manifest paths must remain relative to the artifact root")
        if any(character in relative for character in ("\n", "\r", "\\")):
            raise ValueError("artifact manifest path contains unsupported characters")
        if relative in seen:
            raise ValueError("artifact manifest contains duplicate paths")
        if previous_relative is not None and relative <= previous_relative:
            raise ValueError("artifact manifest paths must be strictly sorted")
        seen.add(relative)
        previous_relative = relative

        file_path = root_path.joinpath(*pure_relative.parts)
        if file_path.is_symlink() or not file_path.is_file():
            raise ValueError(f"artifact manifest file is missing or unsafe: {relative}")
        if not file_path.resolve().is_relative_to(root_path):
            raise ValueError(f"artifact manifest path escapes the artifact root: {relative}")
        if _sha256_file(file_path) != expected:
            raise ValueError(f"artifact manifest digest mismatch: {relative}")


def build_manifest(root: str | Path, output_name: str = _DEFAULT_OUTPUT_NAME) -> str:
    root_path = Path(root).resolve(strict=True)
    if not root_path.is_dir():
        raise ValueError("artifact root must be a directory")
    output_name = _validated_output_name(output_name)
    temporary_name = f"{output_name}.tmp"
    manifest_path = root_path / output_name
    temporary_path = root_path / temporary_name

    files = _manifest_files(root_path, output_name, temporary_name)
    if not files:
        raise ValueError("artifact root must contain at least one file")
    lines = [f"{_sha256_file(path)}  {path.relative_to(root_path).as_posix()}\n" for path in files]
    try:
        temporary_path.write_text("".join(lines), encoding="utf-8", newline="\n")
        os.replace(temporary_path, manifest_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    verify_manifest(root_path, output_name)
    return _sha256_file(manifest_path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, artifact-root-relative SHA-256 manifest."
    )
    parser.add_argument("--root", required=True, help="Artifact directory to hash")
    parser.add_argument(
        "--output-name",
        default=_DEFAULT_OUTPUT_NAME,
        help="Manifest file name written inside the artifact directory",
    )
    return parser


def main() -> None:
    arguments = _build_parser().parse_args()
    print(build_manifest(arguments.root, arguments.output_name))


if __name__ == "__main__":
    main()
