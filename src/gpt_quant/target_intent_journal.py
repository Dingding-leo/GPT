from __future__ import annotations

import errno
import hashlib
import os
import stat
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX platforms
    _fcntl = None

from ._atomic_publish import publish_staged_paths_atomically
from .execution_intent import TargetPositionIntent

_STAGING_PREFIX = ".target-intent-journal-"
_ERROR_LABEL = "target-position intent journal"
_PRIVATE_FILE_MODE = 0o600
_READ_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class TargetPositionIntentJournal:
    """Canonical, replay-verified collection of immutable target-position intents."""

    intents: tuple[TargetPositionIntent, ...]
    sha256: str

    @property
    def count(self) -> int:
        return len(self.intents)

    def to_bytes(self) -> bytes:
        return b"".join(intent.to_json_bytes() for intent in self.intents)


def _decision_key(intent: TargetPositionIntent) -> tuple[object, ...]:
    return (
        intent.instrument_id,
        intent.bar,
        intent.strategy_id,
        intent.signal_bar_open_utc,
        intent.signal_bar_close_utc,
    )


def _sort_key(intent: TargetPositionIntent) -> tuple[object, ...]:
    return (
        intent.decision_not_before_utc,
        intent.instrument_id,
        intent.bar,
        intent.strategy_id,
        intent.intent_id,
    )


def _journal_from_intents(
    intents: tuple[TargetPositionIntent, ...],
) -> TargetPositionIntentJournal:
    ordered = tuple(sorted(intents, key=_sort_key))
    seen_ids: set[str] = set()
    decisions: dict[tuple[object, ...], str] = {}
    for intent in ordered:
        if intent.intent_id in seen_ids:
            raise ValueError(f"{_ERROR_LABEL} contains duplicate intent ID {intent.intent_id}")
        seen_ids.add(intent.intent_id)

        decision = _decision_key(intent)
        previous_id = decisions.get(decision)
        if previous_id is not None and previous_id != intent.intent_id:
            raise ValueError(f"{_ERROR_LABEL} contains conflicting intents for one signal decision")
        decisions[decision] = intent.intent_id

    payload = b"".join(intent.to_json_bytes() for intent in ordered)
    return TargetPositionIntentJournal(
        intents=ordered,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _parse_journal_bytes(value: bytes) -> TargetPositionIntentJournal:
    if not value:
        raise ValueError(f"{_ERROR_LABEL} must not be empty")

    lines = value.splitlines(keepends=True)
    if any(not line.endswith(b"\n") or line == b"\n" for line in lines):
        raise ValueError(f"{_ERROR_LABEL} must contain canonical newline-terminated intents")

    journal = _journal_from_intents(
        tuple(TargetPositionIntent.from_json_bytes(line) for line in lines)
    )
    if journal.to_bytes() != value:
        raise ValueError(f"{_ERROR_LABEL} entries must use canonical chronological ordering")
    return journal


def _same_inode(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _validate_private_descriptor(descriptor: int, *, label: str) -> os.stat_result:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise ValueError(f"{label} must be a regular single-link file")
    if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
        raise ValueError(f"{label} must be owned by the current user")
    if stat.S_IMODE(file_stat.st_mode) != _PRIVATE_FILE_MODE:
        raise ValueError(f"{label} must use owner-only mode 0600")
    return file_stat


def _read_private_journal_bytes(path: Path) -> bytes:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    non_blocking = getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, os.O_RDONLY | no_follow | non_blocking)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"{_ERROR_LABEL} must not be a symbolic link") from exc
        raise

    try:
        initial_stat = _validate_private_descriptor(descriptor, label=_ERROR_LABEL)
        chunks: list[bytes] = []
        while True:
            try:
                chunk = os.read(descriptor, _READ_CHUNK_SIZE)
            except InterruptedError:
                continue
            if not chunk:
                break
            chunks.append(chunk)

        final_stat = _validate_private_descriptor(descriptor, label=_ERROR_LABEL)
        if (
            final_stat.st_size != initial_stat.st_size
            or final_stat.st_mtime_ns != initial_stat.st_mtime_ns
            or final_stat.st_ctime_ns != initial_stat.st_ctime_ns
        ):
            raise RuntimeError(f"{_ERROR_LABEL} changed during replay")
        try:
            path_stat = os.stat(path, follow_symlinks=False)
        except FileNotFoundError as exc:
            raise RuntimeError(f"{_ERROR_LABEL} path changed during replay") from exc
        if not _same_inode(initial_stat, path_stat):
            raise RuntimeError(f"{_ERROR_LABEL} path changed during replay")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _write_private_file(path: Path, payload: bytes) -> None:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(
        path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | no_follow,
        _PRIVATE_FILE_MODE,
    )
    try:
        os.fchmod(descriptor, _PRIVATE_FILE_MODE)
        remaining = memoryview(payload)
        while remaining:
            try:
                written = os.write(descriptor, remaining)
            except InterruptedError:
                continue
            if written <= 0:
                raise OSError("failed to write target-position intent journal staging file")
            remaining = remaining[written:]
        os.fsync(descriptor)
        _validate_private_descriptor(descriptor, label=f"{_ERROR_LABEL} staging file")
    finally:
        os.close(descriptor)


def publish_payloads_atomically(
    output: Path,
    paths: Mapping[str, Path],
    payloads: Mapping[str, bytes],
    *,
    commit_order: Sequence[str],
    staging_prefix: str,
    error_label: str,
) -> dict[str, Path]:
    """Publish owner-only payload files through the shared atomic transaction."""

    if set(payloads) != set(paths):
        raise ValueError(f"{error_label} payloads must exactly match the destination file set")

    def stage_paths(staging: Path) -> dict[str, Path]:
        staged_paths = {name: staging / path.name for name, path in paths.items()}
        for name, staged_path in staged_paths.items():
            _write_private_file(staged_path, payloads[name])
        return staged_paths

    return publish_staged_paths_atomically(
        output,
        paths,
        stage_paths=stage_paths,
        commit_order=commit_order,
        staging_prefix=staging_prefix,
        error_label=error_label,
    )


def _validate_lock_descriptor(descriptor: int) -> os.stat_result:
    lock_stat = os.fstat(descriptor)
    if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
        raise ValueError(f"{_ERROR_LABEL} writer lock must be a regular single-link file")
    if hasattr(os, "geteuid") and lock_stat.st_uid != os.geteuid():
        raise ValueError(f"{_ERROR_LABEL} writer lock must be owned by the current user")
    os.fchmod(descriptor, _PRIVATE_FILE_MODE)
    return lock_stat


@contextmanager
def _exclusive_writer_lock(journal_path: Path) -> Iterator[None]:
    output = journal_path.parent
    output_preexisted = output.exists()
    if output.is_symlink():
        raise ValueError(f"{_ERROR_LABEL} output directory must not be a symbolic link")
    output.mkdir(parents=True, exist_ok=True)

    lock_path = output / f".{journal_path.name}.lock"
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if _fcntl is None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | no_follow
        try:
            descriptor = os.open(lock_path, flags, _PRIVATE_FILE_MODE)
        except FileExistsError as exc:
            raise RuntimeError(f"{_ERROR_LABEL} writer lock already exists") from exc
        os.close(descriptor)
        try:
            yield
        finally:
            lock_path.unlink(missing_ok=True)
            if not output_preexisted:
                with suppress(OSError):
                    output.rmdir()
        return

    flags = os.O_CREAT | os.O_RDWR | no_follow
    descriptor = os.open(lock_path, flags, _PRIVATE_FILE_MODE)
    acquired = False
    lock_stat: os.stat_result | None = None
    try:
        lock_stat = _validate_lock_descriptor(descriptor)
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"{_ERROR_LABEL} writer lock already exists") from exc
        acquired = True
        os.ftruncate(descriptor, 0)
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.fsync(descriptor)
        yield
    finally:
        if acquired:
            try:
                current_stat = os.stat(lock_path, follow_symlinks=False)
                if lock_stat is None or not _same_inode(lock_stat, current_stat):
                    raise RuntimeError(f"{_ERROR_LABEL} writer lock path changed during commit")
                lock_path.unlink()
            finally:
                _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        os.close(descriptor)
        if not output_preexisted:
            with suppress(OSError):
                output.rmdir()


def load_target_position_intent_journal(
    path: str | Path,
) -> TargetPositionIntentJournal:
    """Load and fully replay-verify one owner-only target-position intent journal."""

    journal_path = Path(path)
    return _parse_journal_bytes(_read_private_journal_bytes(journal_path))


def record_target_position_intent(
    path: str | Path,
    intent: TargetPositionIntent,
) -> TargetPositionIntentJournal:
    """Persist one target intent atomically and idempotently.

    A signal decision may have only one target. Recording the same canonical intent is a
    no-op; a different target for the same signal window fails closed.
    """

    if not isinstance(intent, TargetPositionIntent):
        raise TypeError("intent must be a TargetPositionIntent")

    journal_path = Path(path)
    with _exclusive_writer_lock(journal_path):
        if journal_path.exists():
            journal = load_target_position_intent_journal(journal_path)
            matching = next(
                (
                    existing
                    for existing in journal.intents
                    if existing.intent_id == intent.intent_id
                ),
                None,
            )
            if matching is not None and matching.to_json_bytes() != intent.to_json_bytes():
                raise ValueError(f"{_ERROR_LABEL} intent ID maps to conflicting bytes")
            if matching is not None:
                return journal
            intents = (*journal.intents, intent)
        else:
            intents = (intent,)

        updated = _journal_from_intents(tuple(intents))
        publish_payloads_atomically(
            journal_path.parent,
            {"journal": journal_path},
            {"journal": updated.to_bytes()},
            commit_order=("journal",),
            staging_prefix=_STAGING_PREFIX,
            error_label=_ERROR_LABEL,
        )
        persisted = load_target_position_intent_journal(journal_path)
        if persisted != updated:
            raise RuntimeError(f"{_ERROR_LABEL} changed during publication")
        return persisted
