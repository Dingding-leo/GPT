from __future__ import annotations

import os
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory

PathStager = Callable[[Path], Mapping[str, Path]]


def _validated_contract(
    output: Path,
    paths: Mapping[str, Path],
    *,
    commit_order: Sequence[str],
    staging_prefix: str,
    error_label: str,
) -> tuple[str, ...]:
    names = set(paths)
    ordered_names = tuple(commit_order)
    if len(ordered_names) != len(names) or set(ordered_names) != names:
        raise ValueError(f"{error_label} commit order must exactly match the destination file set")
    if len(set(paths.values())) != len(paths):
        raise ValueError(f"{error_label} destination paths must be unique")
    if not staging_prefix or Path(staging_prefix).name != staging_prefix:
        raise ValueError("staging_prefix must be a non-empty filename prefix")
    if any(path.parent != output for path in paths.values()):
        raise ValueError(
            f"{error_label} destinations must be direct children of the output directory"
        )
    return ordered_names


def publish_staged_paths_atomically(
    output: Path,
    paths: Mapping[str, Path],
    *,
    stage_paths: PathStager,
    commit_order: Sequence[str],
    staging_prefix: str,
    error_label: str,
) -> dict[str, Path]:
    """Publish one logical artifact set with recoverable reverse-order rollback."""

    ordered_names = _validated_contract(
        output,
        paths,
        commit_order=commit_order,
        staging_prefix=staging_prefix,
        error_label=error_label,
    )
    names = set(paths)
    output_preexisted = output.exists()
    output.mkdir(parents=True, exist_ok=True)
    previous_payloads = {
        name: path.read_bytes() if path.exists() else None for name, path in paths.items()
    }

    try:
        with TemporaryDirectory(prefix=staging_prefix, dir=output) as staging_name:
            staging = Path(staging_name)
            staged_paths = {name: Path(path) for name, path in stage_paths(staging).items()}
            if set(staged_paths) != names:
                raise ValueError(
                    f"{error_label} staged paths must exactly match the destination file set"
                )
            if len(set(staged_paths.values())) != len(staged_paths):
                raise ValueError(f"{error_label} staged paths must be unique")
            if any(path.parent != staging for path in staged_paths.values()):
                raise ValueError(
                    f"{error_label} staged paths must be direct children of the staging directory"
                )
            if any(
                path.is_symlink() or not path.is_file() for path in staged_paths.values()
            ):
                raise ValueError(f"{error_label} staged paths must be regular files")

            replaced: list[str] = []
            try:
                for name in ordered_names:
                    os.replace(staged_paths[name], paths[name])
                    replaced.append(name)
            except BaseException as commit_error:
                rollback_errors: list[str] = []
                for name in reversed(replaced):
                    destination = paths[name]
                    previous_payload = previous_payloads[name]
                    try:
                        if previous_payload is None:
                            destination.unlink(missing_ok=True)
                        else:
                            restore_path = staging / f"restore-{destination.name}"
                            restore_path.write_bytes(previous_payload)
                            os.replace(restore_path, destination)
                    except OSError as rollback_error:
                        rollback_errors.append(f"{name}: {rollback_error}")
                if rollback_errors:
                    details = "; ".join(rollback_errors)
                    raise RuntimeError(
                        f"{error_label} commit failed and rollback was incomplete: {details}"
                    ) from commit_error
                raise
    except BaseException:
        if not output_preexisted:
            with suppress(OSError):
                output.rmdir()
        raise

    return dict(paths)


def publish_payloads_atomically(
    output: Path,
    paths: Mapping[str, Path],
    payloads: Mapping[str, bytes],
    *,
    commit_order: Sequence[str],
    staging_prefix: str,
    error_label: str,
) -> dict[str, Path]:
    """Stage byte payloads and delegate publication to the shared transaction."""

    if set(payloads) != set(paths):
        raise ValueError(f"{error_label} payloads must exactly match the destination file set")

    def stage_payloads(staging: Path) -> dict[str, Path]:
        staged_paths = {name: staging / path.name for name, path in paths.items()}
        for name, staged_path in staged_paths.items():
            staged_path.write_bytes(payloads[name])
        return staged_paths

    return publish_staged_paths_atomically(
        output,
        paths,
        stage_paths=stage_payloads,
        commit_order=commit_order,
        staging_prefix=staging_prefix,
        error_label=error_label,
    )
