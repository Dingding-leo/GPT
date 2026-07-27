from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterable, Iterator
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
_MAX_JOURNAL_BYTES = 64 * 1024 * 1024
_MAX_JOURNAL_RECORDS = 65_536
_MAX_INTENT_RECORD_BYTES = 16 * 1024
_READ_CHUNK_BYTES = 1024 * 1024


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
    if len(intents) > _MAX_JOURNAL_RECORDS:
        raise ValueError(f"{_ERROR_LABEL} exceeds the maximum record count")

    ordered = tuple(sorted(intents, key=_sort_key))
    seen_ids: set[str] = set()
    decisions: dict[tuple[object, ...], str] = {}
    digest = hashlib.sha256()
    total_bytes = 0
    for intent in ordered:
        if intent.intent_id in seen_ids:
            raise ValueError(f"{_ERROR_LABEL} contains duplicate intent ID {intent.intent_id}")
        seen_ids.add(intent.intent_id)

        decision = _decision_key(intent)
        previous_id = decisions.get(decision)
        if previous_id is not None and previous_id != intent.intent_id:
            raise ValueError(f"{_ERROR_LABEL} contains conflicting intents for one signal decision")
        decisions[decision] = intent.intent_id

        serialized = intent.to_json_bytes()
        if len(serialized) > _MAX_INTENT_RECORD_BYTES:
            raise ValueError(f"{_ERROR_LABEL} exceeds the maximum record byte size")
        total_bytes += len(serialized)
        if total_bytes > _MAX_JOURNAL_BYTES:
            raise ValueError(f"{_ERROR_LABEL} exceeds the maximum byte size")
        digest.update(serialized)

    return TargetPositionIntentJournal(
        intents=ordered,
        sha256=digest.hexdigest(),
    )


def _parse_journal_chunks(chunks: Iterable[bytes]) -> TargetPositionIntentJournal:
    intents: list[TargetPositionIntent] = []
    pending = bytearray()
    total_bytes = 0

    for chunk in chunks:
        if not chunk:
            continue
        total_bytes += len(chunk)
        if total_bytes > _MAX_JOURNAL_BYTES:
            raise ValueError(f"{_ERROR_LABEL} exceeds the maximum byte size")
        pending.extend(chunk)

        while True:
            newline_index = pending.find(b"\n")
            if newline_index < 0:
                break
            line_size = newline_index + 1
            if line_size > _MAX_INTENT_RECORD_BYTES:
                raise ValueError(f"{_ERROR_LABEL} exceeds the maximum record byte size")
            line = bytes(pending[:line_size])
            del pending[:line_size]
            if line == b"\n":
                raise ValueError(
                    f"{_ERROR_LABEL} must contain canonical newline-terminated intents"
                )
            if len(intents) >= _MAX_JOURNAL_RECORDS:
                raise ValueError(f"{_ERROR_LABEL} exceeds the maximum record count")
            intents.append(TargetPositionIntent.from_json_bytes(line))

        if len(pending) > _MAX_INTENT_RECORD_BYTES:
            raise ValueError(f"{_ERROR_LABEL} exceeds the maximum record byte size")

    if pending:
        raise ValueError(f"{_ERROR_LABEL} must contain canonical newline-terminated intents")
    if not intents:
        raise ValueError(f"{_ERROR_LABEL} must not be empty")

    persisted = tuple(intents)
    journal = _journal_from_intents(persisted)
    if journal.intents != persisted:
        raise ValueError(f"{_ERROR_LABEL} entries must use canonical chronological ordering")
    return journal


def _parse_journal_bytes(value: bytes) -> TargetPositionIntentJournal:
    return _parse_journal_chunks((value,))


def _validate_private_parent_directory(parent: Path, *, create: bool) -> None:
    if parent.is_symlink():
        raise ValueError(f"{_ERROR_LABEL} parent directory must not be a symbolic link")
    if create:
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(parent, flags)
    try:
        parent_stat = os.fstat(descriptor)
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise ValueError(f"{_ERROR_LABEL} parent must be a directory")
        if hasattr(os, "geteuid") and parent_stat.st_uid != os.geteuid():
            raise ValueError(
                f"{_ERROR_LABEL} parent directory must be owned by the current user"
            )
        if stat.S_IMODE(parent_stat.st_mode) & 0o022:
            raise ValueError(
                f"{_ERROR_LABEL} parent directory must not be group/world writable"
            )

        current_stat = os.stat(parent, follow_symlinks=False)
        if (
            current_stat.st_dev != parent_stat.st_dev
            or current_stat.st_ino != parent_stat.st_ino
        ):
            raise RuntimeError(f"{_ERROR_LABEL} parent directory changed during validation")
    finally:
        os.close(descriptor)


def _validate_journal_descriptor(descriptor: int) -> os.stat_result:
    journal_stat = os.fstat(descriptor)
    if not stat.S_ISREG(journal_stat.st_mode) or journal_stat.st_nlink != 1:
        raise ValueError(f"{_ERROR_LABEL} must be a regular single-link file")
    if hasattr(os, "geteuid") and journal_stat.st_uid != os.geteuid():
        raise ValueError(f"{_ERROR_LABEL} must be owned by the current user")
    if stat.S_IMODE(journal_stat.st_mode) != 0o600:
        raise ValueError(f"{_ERROR_LABEL} must use owner-only 0600 permissions")
    if journal_stat.st_size > _MAX_JOURNAL_BYTES:
        raise ValueError(f"{_ERROR_LABEL} exceeds the maximum byte size")
    return journal_stat


def _read_journal_descriptor(descriptor: int) -> TargetPositionIntentJournal:
    _validate_journal_descriptor(descriptor)

    def chunks() -> Iterator[bytes]:
        while True:
            chunk = os.read(descriptor, _READ_CHUNK_BYTES)
            if not chunk:
                return
            yield chunk

    return _parse_journal_chunks(chunks())


def _validate_lock_descriptor(descriptor: int) -> os.stat_result:
    lock_stat = os.fstat(descriptor)
    if not stat.S_ISREG(lock_stat.st_mode) or lock_stat.st_nlink != 1:
        raise ValueError(f"{_ERROR_LABEL} writer lock must be a regular single-link file")
    if hasattr(os, "geteuid") and lock_stat.st_uid != os.geteuid():
        raise ValueError(f"{_ERROR_LABEL} writer lock must be owned by the current user")
    os.fchmod(descriptor, 0o600)
    return lock_stat


@contextmanager
def _exclusive_writer_lock(journal_path: Path) -> Iterator[None]:
    output = journal_path.parent
    output_preexisted = output.exists()
    _validate_private_parent_directory(output, create=True)

    lock_path = output / f".{journal_path.name}.lock"
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if _fcntl is None:
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | no_follow
        try:
            descriptor = os.open(lock_path, flags, 0o600)
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
    descriptor = os.open(lock_path, flags, 0o600)
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
                if lock_stat is None or (
                    current_stat.st_dev != lock_stat.st_dev
                    or current_stat.st_ino != lock_stat.st_ino
                ):
                    raise RuntimeError(f"{_ERROR_LABEL} writer lock path changed during commit")
                lock_path.unlink()
            finally:
                _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        os.close(descriptor)
        if not output_preexisted:
            with suppress(OSError):
                output.rmdir()


def _publish_journal_payload(journal_path: Path, payload: bytes) -> None:
    def stage_payload(staging: Path) -> dict[str, Path]:
        staged_path = staging / journal_path.name
        staged_path.write_bytes(payload)
        staged_path.chmod(0o600)
        return {"journal": staged_path}

    publish_staged_paths_atomically(
        journal_path.parent,
        {"journal": journal_path},
        stage_paths=stage_payload,
        commit_order=("journal",),
        staging_prefix=_STAGING_PREFIX,
        error_label=_ERROR_LABEL,
    )


def load_target_position_intent_journal(
    path: str | Path,
) -> TargetPositionIntentJournal:
    """Load and fully replay-verify one persisted target-position intent journal."""

    journal_path = Path(path)
    _validate_private_parent_directory(journal_path.parent, create=False)
    descriptor = os.open(
        journal_path,
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        opened_stat = _validate_journal_descriptor(descriptor)
        journal = _read_journal_descriptor(descriptor)
        current_stat = os.stat(journal_path, follow_symlinks=False)
        if (
            current_stat.st_dev != opened_stat.st_dev
            or current_stat.st_ino != opened_stat.st_ino
        ):
            raise RuntimeError(f"{_ERROR_LABEL} path changed during replay")
        final_stat = _validate_journal_descriptor(descriptor)
        if (
            final_stat.st_dev != opened_stat.st_dev
            or final_stat.st_ino != opened_stat.st_ino
            or final_stat.st_size != opened_stat.st_size
            or final_stat.st_mtime_ns != opened_stat.st_mtime_ns
            or final_stat.st_ctime_ns != opened_stat.st_ctime_ns
        ):
            raise RuntimeError(f"{_ERROR_LABEL} contents changed during replay")
        return journal
    finally:
        os.close(descriptor)


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
        _publish_journal_payload(journal_path, updated.to_bytes())
        return updated
