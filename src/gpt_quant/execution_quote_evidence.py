from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - paper/live state is POSIX-only for now
    _fcntl = None

from .execution_quote import ExecutionQuoteSnapshot

_ERROR_LABEL = "execution quote evidence store"
_LOCK_NAME = ".execution-quote-evidence.lock"
_JSON_NAME = re.compile(r"([0-9a-f]{64})\.json")


@dataclass(frozen=True, slots=True)
class ExecutionQuoteEvidenceStore:
    """Replay-verified immutable execution quotes and their deterministic root."""

    snapshots: tuple[ExecutionQuoteSnapshot, ...]
    sha256: str

    @property
    def count(self) -> int:
        return len(self.snapshots)

    def to_bytes(self) -> bytes:
        return b"".join(snapshot.to_json_bytes() for snapshot in self.snapshots)


def _sort_key(snapshot: ExecutionQuoteSnapshot) -> tuple[object, ...]:
    return (
        snapshot.received_at_utc,
        snapshot.observed_at_utc,
        snapshot.provider,
        snapshot.instrument_id,
        snapshot.snapshot_id,
    )


def _store_from_snapshots(
    snapshots: tuple[ExecutionQuoteSnapshot, ...],
) -> ExecutionQuoteEvidenceStore:
    ordered = tuple(sorted(snapshots, key=_sort_key))
    seen_ids: set[str] = set()
    for snapshot in ordered:
        if snapshot.snapshot_id in seen_ids:
            raise ValueError(
                f"{_ERROR_LABEL} contains duplicate snapshot ID {snapshot.snapshot_id}"
            )
        seen_ids.add(snapshot.snapshot_id)
    payload = b"".join(snapshot.to_json_bytes() for snapshot in ordered)
    return ExecutionQuoteEvidenceStore(
        snapshots=ordered,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _validate_directory_descriptor(descriptor: int) -> os.stat_result:
    directory_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ValueError(f"{_ERROR_LABEL} path must be a directory")
    if hasattr(os, "geteuid") and directory_stat.st_uid != os.geteuid():
        raise ValueError(f"{_ERROR_LABEL} directory must be owned by the current user")
    if stat.S_IMODE(directory_stat.st_mode) != 0o700:
        raise ValueError(f"{_ERROR_LABEL} directory must use mode 0700")
    return directory_stat


def _open_private_directory(path: Path) -> tuple[int, os.stat_result]:
    if not path.name or path.name in {".", ".."}:
        raise ValueError(f"{_ERROR_LABEL} path must name one directory")
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_only = getattr(os, "O_DIRECTORY", 0)
    parent_descriptor = os.open(path.parent, os.O_RDONLY | directory_only | no_follow)
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent_descriptor)
        except FileExistsError:
            created = False
        else:
            created = True
        descriptor = os.open(
            path.name,
            os.O_RDONLY | directory_only | no_follow,
            dir_fd=parent_descriptor,
        )
        try:
            if created:
                os.fchmod(descriptor, 0o700)
            directory_stat = _validate_directory_descriptor(descriptor)
            path_stat = os.stat(
                path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                path_stat.st_dev != directory_stat.st_dev
                or path_stat.st_ino != directory_stat.st_ino
            ):
                raise RuntimeError(f"{_ERROR_LABEL} directory path changed while opening")
            if created:
                os.fsync(descriptor)
                os.fsync(parent_descriptor)
            return descriptor, directory_stat
        except BaseException:
            os.close(descriptor)
            raise
    finally:
        os.close(parent_descriptor)


def _validate_regular_private_file(descriptor: int, *, label: str) -> os.stat_result:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise ValueError(f"{label} must be a regular single-link file")
    if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
        raise ValueError(f"{label} must be owned by the current user")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ValueError(f"{label} must use mode 0600")
    return file_stat


def _read_snapshot_file(directory_descriptor: int, name: str) -> ExecutionQuoteSnapshot:
    match = _JSON_NAME.fullmatch(name)
    if match is None:
        raise ValueError(f"{_ERROR_LABEL} contains unexpected entry {name!r}")
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(
        name,
        os.O_RDONLY | no_follow | nonblock,
        dir_fd=directory_descriptor,
    )
    try:
        file_stat = _validate_regular_private_file(
            descriptor,
            label=f"{_ERROR_LABEL} snapshot file",
        )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_stat = os.fstat(descriptor)
        path_stat = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
        if (
            after_stat.st_dev != file_stat.st_dev
            or after_stat.st_ino != file_stat.st_ino
            or after_stat.st_size != file_stat.st_size
            or path_stat.st_dev != file_stat.st_dev
            or path_stat.st_ino != file_stat.st_ino
        ):
            raise RuntimeError(f"{_ERROR_LABEL} snapshot changed during replay")
    finally:
        os.close(descriptor)
    snapshot = ExecutionQuoteSnapshot.from_json_bytes(b"".join(chunks))
    if snapshot.snapshot_id != match.group(1):
        raise ValueError(f"{_ERROR_LABEL} filename does not match canonical snapshot ID")
    return snapshot


def _load_from_descriptor(directory_descriptor: int) -> ExecutionQuoteEvidenceStore:
    names = sorted(name for name in os.listdir(directory_descriptor) if name != _LOCK_NAME)
    snapshots = tuple(_read_snapshot_file(directory_descriptor, name) for name in names)
    return _store_from_snapshots(snapshots)


@contextmanager
def _exclusive_store_lock(path: Path) -> Iterator[tuple[int, os.stat_result]]:
    if _fcntl is None:
        raise RuntimeError(f"{_ERROR_LABEL} requires POSIX advisory locking")
    directory_descriptor, directory_stat = _open_private_directory(path)
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(
        _LOCK_NAME,
        os.O_CREAT | os.O_RDWR | no_follow,
        0o600,
        dir_fd=directory_descriptor,
    )
    acquired = False
    lock_stat: os.stat_result | None = None
    try:
        os.fchmod(descriptor, 0o600)
        lock_stat = _validate_regular_private_file(
            descriptor,
            label=f"{_ERROR_LABEL} writer lock",
        )
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"{_ERROR_LABEL} writer lock is already held") from exc
        acquired = True
        yield directory_descriptor, directory_stat
    finally:
        if acquired:
            current_stat = os.stat(
                _LOCK_NAME,
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            if lock_stat is None or (
                current_stat.st_dev != lock_stat.st_dev
                or current_stat.st_ino != lock_stat.st_ino
            ):
                raise RuntimeError(f"{_ERROR_LABEL} writer lock path changed during use")
            os.unlink(_LOCK_NAME, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
            _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        os.close(descriptor)
        current_directory_stat = os.stat(path, follow_symlinks=False)
        if (
            current_directory_stat.st_dev != directory_stat.st_dev
            or current_directory_stat.st_ino != directory_stat.st_ino
        ):
            os.close(directory_descriptor)
            raise RuntimeError(f"{_ERROR_LABEL} directory path changed during use")
        os.close(directory_descriptor)


def load_execution_quote_evidence_store(
    path: str | Path,
) -> ExecutionQuoteEvidenceStore:
    """Replay every persisted quote and return a deterministic content root."""

    store_path = Path(path)
    with _exclusive_store_lock(store_path) as (directory_descriptor, _):
        return _load_from_descriptor(directory_descriptor)


def record_execution_quote_evidence(
    path: str | Path,
    snapshot: ExecutionQuoteSnapshot,
) -> ExecutionQuoteEvidenceStore:
    """Persist one immutable quote idempotently and replay the complete store."""

    if not isinstance(snapshot, ExecutionQuoteSnapshot):
        raise TypeError("snapshot must be an ExecutionQuoteSnapshot")
    store_path = Path(path)
    destination_name = f"{snapshot.snapshot_id}.json"
    payload = snapshot.to_json_bytes()
    with _exclusive_store_lock(store_path) as (directory_descriptor, _):
        try:
            existing = _read_snapshot_file(directory_descriptor, destination_name)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if existing.to_json_bytes() != payload:
                raise ValueError(f"{_ERROR_LABEL} snapshot ID maps to conflicting bytes")
            return _load_from_descriptor(directory_descriptor)

        temporary_name = f".execution-quote-{os.getpid()}-{token_hex(8)}.tmp"
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        temporary_descriptor = os.open(
            temporary_name,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | no_follow,
            0o600,
            dir_fd=directory_descriptor,
        )
        published = False
        try:
            os.fchmod(temporary_descriptor, 0o600)
            _validate_regular_private_file(
                temporary_descriptor,
                label=f"{_ERROR_LABEL} staged snapshot",
            )
            view = memoryview(payload)
            while view:
                written = os.write(temporary_descriptor, view)
                if written <= 0:
                    raise OSError("failed to write execution quote evidence")
                view = view[written:]
            os.fsync(temporary_descriptor)
            os.link(
                temporary_name,
                destination_name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
            published = True
        finally:
            os.close(temporary_descriptor)
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)

        if not published:
            raise RuntimeError(f"{_ERROR_LABEL} failed to publish snapshot")
        persisted = _read_snapshot_file(directory_descriptor, destination_name)
        if persisted.to_json_bytes() != payload:
            raise RuntimeError(f"{_ERROR_LABEL} replay differs after publication")
        return _load_from_descriptor(directory_descriptor)
