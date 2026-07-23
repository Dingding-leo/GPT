from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX platforms
    _fcntl = None

from ._atomic_publish import publish_payloads_atomically
from .execution_quote_binding import ExecutionQuoteBinding
from .execution_quote_evidence import ExecutionQuoteEvidenceStore
from .target_intent_journal import TargetPositionIntentJournal

_STAGING_PREFIX = ".execution-quote-binding-journal-"
_ERROR_LABEL = "execution quote binding journal"


@dataclass(frozen=True, slots=True)
class ExecutionQuoteBindingJournal:
    """Canonical bindings replayed against persisted intent and quote evidence."""

    bindings: tuple[ExecutionQuoteBinding, ...]
    sha256: str

    @property
    def count(self) -> int:
        return len(self.bindings)

    def to_bytes(self) -> bytes:
        return b"".join(binding.to_json_bytes() for binding in self.bindings)


def _decision_key(binding: ExecutionQuoteBinding) -> tuple[object, ...]:
    return binding.target_intent_id, binding.decision_at_utc


def _sort_key(binding: ExecutionQuoteBinding) -> tuple[object, ...]:
    return (
        binding.decision_at_utc,
        binding.target_intent_id,
        binding.quote_snapshot_id,
        binding.binding_id,
    )


def _journal_from_bindings(
    bindings: tuple[ExecutionQuoteBinding, ...],
) -> ExecutionQuoteBindingJournal:
    ordered = tuple(sorted(bindings, key=_sort_key))
    seen_ids: set[str] = set()
    decisions: dict[tuple[object, ...], str] = {}
    for binding in ordered:
        if binding.binding_id in seen_ids:
            raise ValueError(f"{_ERROR_LABEL} contains duplicate binding ID {binding.binding_id}")
        seen_ids.add(binding.binding_id)

        decision = _decision_key(binding)
        previous_id = decisions.get(decision)
        if previous_id is not None and previous_id != binding.binding_id:
            raise ValueError(f"{_ERROR_LABEL} contains conflicting quotes for one target decision")
        decisions[decision] = binding.binding_id

    payload = b"".join(binding.to_json_bytes() for binding in ordered)
    return ExecutionQuoteBindingJournal(
        bindings=ordered,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _parse_journal_bytes(value: bytes) -> ExecutionQuoteBindingJournal:
    if not value:
        raise ValueError(f"{_ERROR_LABEL} must not be empty")
    lines = value.splitlines(keepends=True)
    if any(not line.endswith(b"\n") or line == b"\n" for line in lines):
        raise ValueError(f"{_ERROR_LABEL} must contain canonical newline-terminated bindings")
    journal = _journal_from_bindings(
        tuple(ExecutionQuoteBinding.from_json_bytes(line) for line in lines)
    )
    if journal.to_bytes() != value:
        raise ValueError(f"{_ERROR_LABEL} entries must use canonical chronological ordering")
    return journal


def _verify_reconstruction(
    journal: ExecutionQuoteBindingJournal,
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
) -> None:
    if not isinstance(intent_journal, TargetPositionIntentJournal):
        raise TypeError("intent_journal must be a TargetPositionIntentJournal")
    if not isinstance(quote_store, ExecutionQuoteEvidenceStore):
        raise TypeError("quote_store must be an ExecutionQuoteEvidenceStore")

    intents = {intent.intent_id: intent for intent in intent_journal.intents}
    quotes = {quote.snapshot_id: quote for quote in quote_store.snapshots}
    for binding in journal.bindings:
        try:
            intent = intents[binding.target_intent_id]
        except KeyError as exc:
            raise ValueError(
                f"{_ERROR_LABEL} references a missing target intent {binding.target_intent_id}"
            ) from exc
        try:
            quote = quotes[binding.quote_snapshot_id]
        except KeyError as exc:
            raise ValueError(
                f"{_ERROR_LABEL} references a missing execution quote {binding.quote_snapshot_id}"
            ) from exc
        binding.assert_reconstructs(intent, quote)


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
    if output.is_symlink():
        raise ValueError(f"{_ERROR_LABEL} output directory must not be a symbolic link")
    output.mkdir(parents=True, exist_ok=True)

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


def load_execution_quote_binding_journal(
    path: str | Path,
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
) -> ExecutionQuoteBindingJournal:
    """Load every binding and reconstruct it from persisted target and quote evidence."""

    journal = _parse_journal_bytes(Path(path).read_bytes())
    _verify_reconstruction(
        journal,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )
    return journal


def record_execution_quote_binding(
    path: str | Path,
    binding: ExecutionQuoteBinding,
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
) -> ExecutionQuoteBindingJournal:
    """Persist one binding only after exact durable source reconstruction succeeds."""

    if not isinstance(binding, ExecutionQuoteBinding):
        raise TypeError("binding must be an ExecutionQuoteBinding")
    candidate = _journal_from_bindings((binding,))
    _verify_reconstruction(
        candidate,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )

    journal_path = Path(path)
    with _exclusive_writer_lock(journal_path):
        if journal_path.exists():
            journal = load_execution_quote_binding_journal(
                journal_path,
                intent_journal=intent_journal,
                quote_store=quote_store,
            )
            matching = next(
                (
                    existing
                    for existing in journal.bindings
                    if existing.binding_id == binding.binding_id
                ),
                None,
            )
            if matching is not None and matching.to_json_bytes() != binding.to_json_bytes():
                raise ValueError(f"{_ERROR_LABEL} binding ID maps to conflicting bytes")
            if matching is not None:
                return journal
            bindings = (*journal.bindings, binding)
        else:
            bindings = (binding,)

        updated = _journal_from_bindings(tuple(bindings))
        _verify_reconstruction(
            updated,
            intent_journal=intent_journal,
            quote_store=quote_store,
        )
        publish_payloads_atomically(
            journal_path.parent,
            {"journal": journal_path},
            {"journal": updated.to_bytes()},
            commit_order=("journal",),
            staging_prefix=_STAGING_PREFIX,
            error_label=_ERROR_LABEL,
        )
        return updated
