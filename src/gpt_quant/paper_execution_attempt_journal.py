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

from .execution_quote_binding_journal import ExecutionQuoteBindingJournal
from .execution_quote_evidence import ExecutionQuoteEvidenceStore
from .paper_execution_attempt import PaperExecutionAttempt
from .target_intent_journal import TargetPositionIntentJournal

_STAGING_PREFIX = ".paper-execution-attempt-journal-"
_STAGE_NAME = re.compile(r"\.paper-execution-attempt-journal-[0-9]+-[0-9a-f]{16}\.tmp")
_ERROR_LABEL = "paper execution attempt journal"


@dataclass(frozen=True, slots=True)
class PaperExecutionAttemptJournal:
    """Canonical paper outcomes replayed from exact intent, quote, and binding evidence."""

    attempts: tuple[PaperExecutionAttempt, ...]
    sha256: str

    @property
    def count(self) -> int:
        return len(self.attempts)

    def to_bytes(self) -> bytes:
        return b"".join(attempt.to_json_bytes() for attempt in self.attempts)


def _submission_key(attempt: PaperExecutionAttempt) -> tuple[object, ...]:
    return (
        attempt.binding_id,
        attempt.submitted_at_utc,
        attempt.side,
        attempt.requested_base_quantity,
    )


def _sort_key(attempt: PaperExecutionAttempt) -> tuple[object, ...]:
    return (
        attempt.submitted_at_utc,
        attempt.outcome_at_utc,
        attempt.instrument_id,
        attempt.binding_id,
        attempt.attempt_id,
    )


def _journal_from_attempts(
    attempts: tuple[PaperExecutionAttempt, ...],
) -> PaperExecutionAttemptJournal:
    ordered = tuple(sorted(attempts, key=_sort_key))
    seen_ids: set[str] = set()
    submissions: dict[tuple[object, ...], str] = {}
    for attempt in ordered:
        if attempt.attempt_id in seen_ids:
            raise ValueError(f"{_ERROR_LABEL} contains duplicate attempt ID {attempt.attempt_id}")
        seen_ids.add(attempt.attempt_id)

        submission = _submission_key(attempt)
        previous_id = submissions.get(submission)
        if previous_id is not None and previous_id != attempt.attempt_id:
            raise ValueError(f"{_ERROR_LABEL} contains conflicting outcomes for one submission")
        submissions[submission] = attempt.attempt_id

    payload = b"".join(attempt.to_json_bytes() for attempt in ordered)
    return PaperExecutionAttemptJournal(
        attempts=ordered,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _parse_journal_bytes(value: bytes) -> PaperExecutionAttemptJournal:
    if not value:
        raise ValueError(f"{_ERROR_LABEL} must not be empty")
    lines = value.splitlines(keepends=True)
    if any(not line.endswith(b"\n") or line == b"\n" for line in lines):
        raise ValueError(f"{_ERROR_LABEL} must contain canonical newline-terminated attempts")
    journal = _journal_from_attempts(
        tuple(PaperExecutionAttempt.from_json_bytes(line) for line in lines)
    )
    if journal.to_bytes() != value:
        raise ValueError(f"{_ERROR_LABEL} entries must use canonical chronological ordering")
    return journal


def _verify_reconstruction(
    journal: PaperExecutionAttemptJournal,
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
    binding_journal: ExecutionQuoteBindingJournal,
) -> None:
    if not isinstance(intent_journal, TargetPositionIntentJournal):
        raise TypeError("intent_journal must be a TargetPositionIntentJournal")
    if not isinstance(quote_store, ExecutionQuoteEvidenceStore):
        raise TypeError("quote_store must be an ExecutionQuoteEvidenceStore")
    if not isinstance(binding_journal, ExecutionQuoteBindingJournal):
        raise TypeError("binding_journal must be an ExecutionQuoteBindingJournal")

    intents = {intent.intent_id: intent for intent in intent_journal.intents}
    quotes = {quote.snapshot_id: quote for quote in quote_store.snapshots}
    bindings = {binding.binding_id: binding for binding in binding_journal.bindings}

    for binding in binding_journal.bindings:
        try:
            intent = intents[binding.target_intent_id]
        except KeyError as exc:
            raise ValueError(
                f"{_ERROR_LABEL} binding evidence references a missing target intent "
                f"{binding.target_intent_id}"
            ) from exc
        try:
            quote = quotes[binding.quote_snapshot_id]
        except KeyError as exc:
            raise ValueError(
                f"{_ERROR_LABEL} binding evidence references a missing execution quote "
                f"{binding.quote_snapshot_id}"
            ) from exc
        binding.assert_reconstructs(intent, quote)

    for attempt in journal.attempts:
        try:
            binding = bindings[attempt.binding_id]
        except KeyError as exc:
            raise ValueError(
                f"{_ERROR_LABEL} references a missing execution binding {attempt.binding_id}"
            ) from exc
        try:
            quote = quotes[attempt.quote_snapshot_id]
        except KeyError as exc:
            raise ValueError(
                f"{_ERROR_LABEL} references a missing execution quote {attempt.quote_snapshot_id}"
            ) from exc
        try:
            intent = intents[binding.target_intent_id]
        except KeyError as exc:
            raise ValueError(
                f"{_ERROR_LABEL} references a missing target intent {binding.target_intent_id}"
            ) from exc
        attempt.assert_reconstructs(intent, binding, quote)


def _validate_directory_descriptor(descriptor: int) -> os.stat_result:
    directory_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ValueError(f"{_ERROR_LABEL} output path must be a directory")
    if hasattr(os, "geteuid") and directory_stat.st_uid != os.geteuid():
        raise ValueError(f"{_ERROR_LABEL} output directory must be owned by the current user")
    if stat.S_IMODE(directory_stat.st_mode) & 0o022:
        raise ValueError(f"{_ERROR_LABEL} output directory must not be group/world-writable")
    return directory_stat


def _open_output_directory(path: Path, *, create: bool) -> tuple[int, os.stat_result, bool]:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    directory_only = getattr(os, "O_DIRECTORY", 0)
    flags = os.O_RDONLY | directory_only | no_follow
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError:
        if not create:
            raise
        if not path.name or path.name in {".", ".."}:
            raise ValueError(f"{_ERROR_LABEL} output path must name one directory") from None
        parent_descriptor = os.open(path.parent, flags)
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent_descriptor)
            descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
        created = True
    else:
        created = False

    try:
        directory_stat = _validate_directory_descriptor(descriptor)
        path_stat = os.stat(path, follow_symlinks=False)
        if path_stat.st_dev != directory_stat.st_dev or path_stat.st_ino != directory_stat.st_ino:
            raise RuntimeError(f"{_ERROR_LABEL} output directory path changed while opening")
        return descriptor, directory_stat, created
    except BaseException:
        os.close(descriptor)
        raise


def _validate_private_file_descriptor(descriptor: int, *, label: str) -> os.stat_result:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise ValueError(f"{label} must be a regular single-link file")
    if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
        raise ValueError(f"{label} must be owned by the current user")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ValueError(f"{label} must use mode 0600")
    return file_stat


def _read_private_journal(directory_descriptor: int, name: str) -> bytes:
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(
            name,
            os.O_RDONLY | no_follow | nonblock,
            dir_fd=directory_descriptor,
        )
    except OSError as exc:
        raise ValueError(f"{_ERROR_LABEL} file must be a private regular file") from exc
    try:
        file_stat = _validate_private_file_descriptor(
            descriptor,
            label=f"{_ERROR_LABEL} file",
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
            raise RuntimeError(f"{_ERROR_LABEL} file changed during replay")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _verify_directory_path(path: Path, expected: os.stat_result) -> None:
    current = os.stat(path, follow_symlinks=False)
    if current.st_dev != expected.st_dev or current.st_ino != expected.st_ino:
        raise RuntimeError(f"{_ERROR_LABEL} output directory path changed during use")


def _recover_stale_stages(directory_descriptor: int) -> None:
    recovered = False
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    nonblock = getattr(os, "O_NONBLOCK", 0)
    for name in sorted(os.listdir(directory_descriptor)):
        if _STAGE_NAME.fullmatch(name) is None:
            continue
        try:
            descriptor = os.open(
                name,
                os.O_RDONLY | no_follow | nonblock,
                dir_fd=directory_descriptor,
            )
        except OSError as exc:
            raise ValueError(f"{_ERROR_LABEL} staged file must be a private regular file") from exc
        try:
            staged_stat = _validate_private_file_descriptor(
                descriptor,
                label=f"{_ERROR_LABEL} staged file",
            )
            path_stat = os.stat(name, dir_fd=directory_descriptor, follow_symlinks=False)
            if path_stat.st_dev != staged_stat.st_dev or path_stat.st_ino != staged_stat.st_ino:
                raise RuntimeError(f"{_ERROR_LABEL} staged file changed during recovery")
        finally:
            os.close(descriptor)
        os.unlink(name, dir_fd=directory_descriptor)
        recovered = True
    if recovered:
        os.fsync(directory_descriptor)


def _validate_lock_descriptor(descriptor: int) -> os.stat_result:
    os.fchmod(descriptor, 0o600)
    return _validate_private_file_descriptor(
        descriptor,
        label=f"{_ERROR_LABEL} writer lock",
    )


@contextmanager
def _exclusive_writer_lock(
    journal_path: Path,
) -> Iterator[tuple[int, os.stat_result]]:
    if _fcntl is None:
        raise RuntimeError(f"{_ERROR_LABEL} requires POSIX advisory locking")
    if not journal_path.name or journal_path.name in {".", ".."}:
        raise ValueError(f"{_ERROR_LABEL} path must name one file")

    output = journal_path.parent
    directory_descriptor, directory_stat, created = _open_output_directory(output, create=True)
    lock_name = f".{journal_path.name}.lock"
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(
        lock_name,
        os.O_CREAT | os.O_RDWR | no_follow,
        0o600,
        dir_fd=directory_descriptor,
    )
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
        _recover_stale_stages(directory_descriptor)
        yield directory_descriptor, directory_stat
    finally:
        if acquired:
            try:
                current_stat = os.stat(
                    lock_name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if lock_stat is None or (
                    current_stat.st_dev != lock_stat.st_dev
                    or current_stat.st_ino != lock_stat.st_ino
                ):
                    raise RuntimeError(f"{_ERROR_LABEL} writer lock path changed during commit")
                os.unlink(lock_name, dir_fd=directory_descriptor)
                os.fsync(directory_descriptor)
            finally:
                _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        os.close(descriptor)
        try:
            _verify_directory_path(output, directory_stat)
        finally:
            os.close(directory_descriptor)
        if created and not journal_path.exists():
            with suppress(OSError):
                output.rmdir()


def _publish_private_journal(
    directory_descriptor: int,
    journal_name: str,
    payload: bytes,
) -> None:
    temporary_name = f"{_STAGING_PREFIX}{os.getpid()}-{token_hex(8)}.tmp"
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(
        temporary_name,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | no_follow,
        0o600,
        dir_fd=directory_descriptor,
    )
    published = False
    try:
        os.fchmod(descriptor, 0o600)
        _validate_private_file_descriptor(
            descriptor,
            label=f"{_ERROR_LABEL} staged file",
        )
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError(f"failed to write {_ERROR_LABEL}")
            view = view[written:]
        os.fsync(descriptor)
        os.replace(
            temporary_name,
            journal_name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        published = True
        os.fsync(directory_descriptor)
    finally:
        os.close(descriptor)
        if not published:
            with suppress(FileNotFoundError):
                os.unlink(temporary_name, dir_fd=directory_descriptor)

    if _read_private_journal(directory_descriptor, journal_name) != payload:
        raise RuntimeError(f"{_ERROR_LABEL} replay differed after publication")


def load_paper_execution_attempt_journal(
    path: str | Path,
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
    binding_journal: ExecutionQuoteBindingJournal,
) -> PaperExecutionAttemptJournal:
    """Replay every attempt from the exact persisted intent, quote, and binding chain."""

    journal_path = Path(path)
    with _exclusive_writer_lock(journal_path) as (directory_descriptor, _):
        journal = _parse_journal_bytes(
            _read_private_journal(directory_descriptor, journal_path.name)
        )
        _verify_reconstruction(
            journal,
            intent_journal=intent_journal,
            quote_store=quote_store,
            binding_journal=binding_journal,
        )
        return journal


def record_paper_execution_attempt_evidence(
    path: str | Path,
    attempt: PaperExecutionAttempt,
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
    binding_journal: ExecutionQuoteBindingJournal,
) -> PaperExecutionAttemptJournal:
    """Persist one outcome only after the complete durable decision chain reconstructs."""

    if not isinstance(attempt, PaperExecutionAttempt):
        raise TypeError("attempt must be a PaperExecutionAttempt")
    candidate = _journal_from_attempts((attempt,))
    _verify_reconstruction(
        candidate,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )

    journal_path = Path(path)
    with _exclusive_writer_lock(journal_path) as (directory_descriptor, _):
        try:
            journal_payload = _read_private_journal(directory_descriptor, journal_path.name)
        except FileNotFoundError:
            journal = None
        except ValueError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                journal = None
            else:
                raise
        else:
            journal = _parse_journal_bytes(journal_payload)
            _verify_reconstruction(
                journal,
                intent_journal=intent_journal,
                quote_store=quote_store,
                binding_journal=binding_journal,
            )

        if journal is not None:
            matching = next(
                (
                    existing
                    for existing in journal.attempts
                    if existing.attempt_id == attempt.attempt_id
                ),
                None,
            )
            if matching is not None and matching.to_json_bytes() != attempt.to_json_bytes():
                raise ValueError(f"{_ERROR_LABEL} attempt ID maps to conflicting bytes")
            if matching is not None:
                return journal
            attempts = (*journal.attempts, attempt)
        else:
            attempts = (attempt,)

        updated = _journal_from_attempts(tuple(attempts))
        _verify_reconstruction(
            updated,
            intent_journal=intent_journal,
            quote_store=quote_store,
            binding_journal=binding_journal,
        )
        _publish_private_journal(
            directory_descriptor,
            journal_path.name,
            updated.to_bytes(),
        )
        return updated
