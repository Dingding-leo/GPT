from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - non-POSIX only
    _fcntl = None

from . import _paper_decision_store_core as _core
from .execution_intent import TargetPositionIntent
from .paper_order_decision import PaperOrderDecision
from .target_intent_journal import load_target_position_intent_journal

PaperDecisionStoreReplay = _core.PaperDecisionStoreReplay
load_paper_order_decision = _core.load_paper_order_decision

# Preserve the historical store import while the domain class keeps a stable,
# adapter-independent module identity. Legacy pickle globals continue to resolve
# through the module-level alias above.
PaperDecisionStoreReplay.__module__ = __name__

__all__ = [
    "PaperDecisionStoreReplay",
    "PaperOrderDecision",
    "initialize_paper_order_decision_store",
    "load_paper_order_decision",
    "pending_target_position_intents",
    "record_paper_order_decision",
    "replay_paper_order_decision_store",
]

_GENESIS_NAME = ".paper-decision-store.genesis"
_GENESIS_KIND = "paper-order-decision-store"
_GENESIS_MAX_BYTES = 16 * 1024 * 1024
_GENESIS_MAX_TARGETS = _core._MAX_DECISION_STORE_RECORDS
_CLAIM_SUFFIX = ".paper-decision-store.claim"
_CLAIM_KIND = "paper-order-decision-store-claim"
_CLAIM_MAX_BYTES = 16 * 1024
_HEX_DIGITS = frozenset("0123456789abcdef")


def _validate_private_directory(descriptor: int) -> os.stat_result:
    directory_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ValueError("paper decision directory must be a regular directory")
    if hasattr(os, "geteuid") and directory_stat.st_uid != os.geteuid():
        raise ValueError("paper decision directory must be owned by the current user")
    directory_mode = stat.S_IMODE(directory_stat.st_mode)
    if directory_mode & 0o022:
        raise ValueError("paper decision directory must not be group/world writable")
    if directory_mode != 0o700:
        raise ValueError("paper decision directory must use owner-only 0700 permissions")
    return directory_stat


@contextmanager
def _opened_parent_directory(directory: Path) -> Iterator[int]:
    parent = directory.parent
    descriptor = os.open(
        parent,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise ValueError("paper decision parent must be a regular directory")
        current = os.stat(parent, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("paper decision parent changed during store creation")
        yield descriptor
        current = os.stat(parent, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("paper decision parent changed during store creation")
    finally:
        os.close(descriptor)


def _fsync_parent_directory_entry(directory: Path) -> None:
    with _opened_parent_directory(directory) as descriptor:
        os.fsync(descriptor)


def _assert_directory_identity(directory: Path, opened: os.stat_result) -> None:
    current = os.stat(directory, follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode) or (opened.st_dev, opened.st_ino) != (
        current.st_dev,
        current.st_ino,
    ):
        raise RuntimeError("paper decision directory changed during operation")


def _bounded_initialization_inventory(directory_descriptor: int) -> tuple[bool, bool]:
    inventory_flags = 0
    with os.scandir(directory_descriptor) as entries:
        for entry_count, entry in enumerate(entries, start=1):
            if entry_count > _core._MAX_DECISION_STORE_ENTRIES:
                raise ValueError("paper decision store exceeds the maximum entry count")
            inventory_flags |= 1 if entry.name == _GENESIS_NAME else 2
    return bool(inventory_flags & 1), bool(inventory_flags & 2)


@contextmanager
def _private_decision_directory(
    directory: Path,
    *,
    create: bool,
) -> Iterator[int]:
    if directory.is_symlink():
        raise ValueError("paper decision directory must not be a symbolic link")
    directory_was_missing = not directory.exists()
    if create:
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        if directory_was_missing:
            _fsync_parent_directory_entry(directory)
    elif directory_was_missing:
        raise FileNotFoundError("paper decision store is not initialized")

    descriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = _validate_private_directory(descriptor)
        _assert_directory_identity(directory, opened)
        yield descriptor
        _assert_directory_identity(directory, opened)
    finally:
        os.close(descriptor)


def _json_bytes(payload: dict[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value).issubset(_HEX_DIGITS)


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("paper decision store metadata contains duplicate JSON fields")
        result[key] = value
    return result


def _genesis_payload(target_journal_path: str | Path) -> bytes:
    journal = load_target_position_intent_journal(target_journal_path)
    if journal.count > _GENESIS_MAX_TARGETS:
        raise ValueError("paper decision store genesis exceeds the target count limit")
    payload = _json_bytes(
        {
            "schema_version": 1,
            "store_kind": _GENESIS_KIND,
            "target_intent_count": journal.count,
            "target_intent_ids": [intent.intent_id for intent in journal.intents],
            "target_journal_sha256": journal.sha256,
        }
    )
    if len(payload) > _GENESIS_MAX_BYTES:
        raise ValueError("paper decision store genesis exceeds the size limit")
    return payload


def _claim_name(directory: Path) -> str:
    if not directory.name:
        raise ValueError("paper decision directory must have a final path component")
    return f".{directory.name}{_CLAIM_SUFFIX}"


def _claim_payload(directory: Path, genesis_sha256: str) -> bytes:
    return _json_bytes(
        {
            "decision_directory_name": directory.name,
            "genesis_sha256": genesis_sha256,
            "schema_version": 1,
            "store_instance_id": secrets.token_hex(32),
            "store_kind": _CLAIM_KIND,
        }
    )


def _read_private_bytes_at(
    directory_descriptor: int,
    name: str,
    *,
    label: str,
    maximum_bytes: int = _GENESIS_MAX_BYTES,
    size_error: str = "paper decision store genesis exceeds the size limit",
    path_error: str = "paper decision store genesis path changed during replay",
) -> bytes:
    descriptor = os.open(
        name,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        dir_fd=directory_descriptor,
    )
    try:
        opened = _core._validate_private_file(descriptor, label)
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(
            descriptor,
            min(1024 * 1024, maximum_bytes + 1 - total),
        ):
            chunks.append(chunk)
            total += len(chunk)
            if total > maximum_bytes:
                raise ValueError(size_error)
        current = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError(path_error)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _validate_store_claim_payload(
    directory: Path,
    payload: bytes,
    expected_genesis_sha256: str,
) -> str:
    try:
        decoded = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_fields,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("paper decision store claim must be canonical UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("paper decision store claim must be a JSON object")
    expected_keys = {
        "decision_directory_name",
        "genesis_sha256",
        "schema_version",
        "store_instance_id",
        "store_kind",
    }
    if set(decoded) != expected_keys:
        raise ValueError("paper decision store claim has an invalid schema")
    if decoded["schema_version"] != 1 or decoded["store_kind"] != _CLAIM_KIND:
        raise ValueError("paper decision store claim has an unsupported identity")
    if decoded["decision_directory_name"] != directory.name:
        raise ValueError("paper decision store claim names a different directory")
    if decoded["genesis_sha256"] != expected_genesis_sha256:
        raise ValueError("paper decision store claim does not match the store genesis")
    if not _is_sha256(decoded["store_instance_id"]):
        raise ValueError("paper decision store claim instance ID is invalid")
    if _json_bytes(decoded) != payload:
        raise ValueError("paper decision store claim must use canonical JSON bytes")
    return hashlib.sha256(payload).hexdigest()


def _read_pinned_private_bytes(
    descriptor: int,
    *,
    label: str,
    maximum_bytes: int,
    size_error: str,
) -> tuple[os.stat_result, bytes]:
    opened = _core._validate_private_file(descriptor, label)
    if opened.st_size > maximum_bytes:
        raise ValueError(size_error)
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while chunk := os.read(descriptor, min(1024 * 1024, maximum_bytes + 1 - total)):
        chunks.append(chunk)
        total += len(chunk)
        if total > maximum_bytes:
            raise ValueError(size_error)
    return opened, b"".join(chunks)


@contextmanager
def _pinned_store_claim(
    directory: Path,
) -> Iterator[Callable[[str], str]]:
    name = _claim_name(directory)
    if _fcntl is None:
        raise RuntimeError("paper decision store claim locking requires POSIX advisory locks")
    with _opened_parent_directory(directory) as parent_descriptor:
        try:
            _fcntl.flock(parent_descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("paper decision store claim lock is held") from exc
        claim_descriptor = -1
        try:
            claim_descriptor = os.open(
                name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
                dir_fd=parent_descriptor,
            )
            opened, initial_payload = _read_pinned_private_bytes(
                claim_descriptor,
                label="paper decision store claim",
                maximum_bytes=_CLAIM_MAX_BYTES,
                size_error="paper decision store claim exceeds the size limit",
            )

            def validate(expected_genesis_sha256: str) -> str:
                try:
                    current = os.stat(
                        name,
                        dir_fd=parent_descriptor,
                        follow_symlinks=False,
                    )
                except FileNotFoundError as exc:
                    raise RuntimeError(
                        "paper decision store claim path changed during validation"
                    ) from exc
                if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                    raise RuntimeError(
                        "paper decision store claim path changed during validation"
                    )
                _, payload = _read_pinned_private_bytes(
                    claim_descriptor,
                    label="paper decision store claim",
                    maximum_bytes=_CLAIM_MAX_BYTES,
                    size_error="paper decision store claim exceeds the size limit",
                )
                if payload != initial_payload:
                    raise RuntimeError(
                        "paper decision store claim bytes changed during validation"
                    )
                return _validate_store_claim_payload(
                    directory,
                    payload,
                    expected_genesis_sha256,
                )

            yield validate
        finally:
            if claim_descriptor >= 0:
                os.close(claim_descriptor)
            _fcntl.flock(parent_descriptor, _fcntl.LOCK_UN)


def _validate_store_claim(directory: Path, expected_genesis_sha256: str) -> str:
    with _pinned_store_claim(directory) as validate:
        return validate(expected_genesis_sha256)


def _write_store_claim(directory: Path, genesis_sha256: str) -> str:
    name = _claim_name(directory)
    payload = _claim_payload(directory, genesis_sha256)
    if _fcntl is None:
        raise RuntimeError("paper decision store claim locking requires POSIX advisory locks")
    with _opened_parent_directory(directory) as parent_descriptor:
        try:
            _fcntl.flock(parent_descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("paper decision store claim lock is held") from exc
        try:
            descriptor = os.open(
                name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
                0o600,
                dir_fd=parent_descriptor,
            )
            try:
                os.fchmod(descriptor, 0o600)
                written = 0
                while written < len(payload):
                    written += os.write(descriptor, payload[written:])
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(parent_descriptor)
        finally:
            _fcntl.flock(parent_descriptor, _fcntl.LOCK_UN)
    return hashlib.sha256(payload).hexdigest()


def _validate_store_genesis(
    target_journal_path: str | Path,
    directory_descriptor: int,
) -> str:
    try:
        os.stat(
            _GENESIS_NAME,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError("paper decision store is not initialized") from exc
    payload = _read_private_bytes_at(
        directory_descriptor,
        _GENESIS_NAME,
        label="paper decision store genesis",
    )
    try:
        decoded = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_fields,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("paper decision store genesis must be canonical UTF-8 JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("paper decision store genesis must be a JSON object")
    expected_keys = {
        "schema_version",
        "store_kind",
        "target_intent_count",
        "target_intent_ids",
        "target_journal_sha256",
    }
    if set(decoded) != expected_keys:
        raise ValueError("paper decision store genesis has an invalid schema")
    if decoded["schema_version"] != 1 or decoded["store_kind"] != _GENESIS_KIND:
        raise ValueError("paper decision store genesis has an unsupported identity")
    count = decoded["target_intent_count"]
    intent_ids = decoded["target_intent_ids"]
    journal_sha256 = decoded["target_journal_sha256"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("paper decision store genesis target count is invalid")
    if count > _GENESIS_MAX_TARGETS:
        raise ValueError("paper decision store genesis exceeds the target count limit")
    if (
        not isinstance(intent_ids, list)
        or len(intent_ids) != count
        or any(not _is_sha256(intent_id) for intent_id in intent_ids)
        or len(set(intent_ids)) != len(intent_ids)
    ):
        raise ValueError("paper decision store genesis target IDs are invalid")
    if not _is_sha256(journal_sha256):
        raise ValueError("paper decision store genesis target journal digest is invalid")
    if _json_bytes(decoded) != payload:
        raise ValueError("paper decision store genesis must use canonical JSON bytes")

    current = load_target_position_intent_journal(target_journal_path)
    current_by_id = {intent.intent_id: intent for intent in current.intents}
    try:
        initial_bytes = b"".join(
            current_by_id[intent_id].to_json_bytes() for intent_id in intent_ids
        )
    except KeyError as exc:
        raise ValueError(
            "target intent journal no longer contains the store genesis state"
        ) from exc
    if hashlib.sha256(initial_bytes).hexdigest() != journal_sha256:
        raise ValueError("target intent journal does not reconstruct the store genesis state")
    return hashlib.sha256(payload).hexdigest()


def initialize_paper_order_decision_store(
    target_journal_path: str | Path,
    decision_directory: str | Path,
) -> str:
    """Explicitly create one empty durable store and return its genesis SHA-256.

    Initialization is the only operation allowed to create the store directory. The
    genesis record binds the empty store to every target intent present at creation;
    ordinary record and replay operations require that exact canonical evidence.
    """

    directory = Path(decision_directory)
    payload = _genesis_payload(target_journal_path)
    genesis_sha256 = hashlib.sha256(payload).hexdigest()
    try:
        claim_sha256 = _validate_store_claim(directory, genesis_sha256)
    except FileNotFoundError:
        claim_sha256 = None
    if claim_sha256 is not None and not directory.exists():
        raise FileNotFoundError(
            "paper decision store recovery authorization is required; "
            "the claimed store directory is missing"
        )

    with _private_decision_directory(directory, create=True) as directory_descriptor:
        has_genesis, has_other_entries = _bounded_initialization_inventory(directory_descriptor)
        if has_genesis:
            if claim_sha256 is None:
                raise FileNotFoundError("paper decision store claim is missing")
            return _validate_store_genesis(target_journal_path, directory_descriptor)
        if has_other_entries:
            raise ValueError("uninitialized paper decision directory must be empty")
        if claim_sha256 is not None:
            raise FileNotFoundError(
                "paper decision store recovery authorization is required; "
                "the claimed store genesis is missing"
            )

        _write_store_claim(directory, genesis_sha256)
        descriptor = os.open(
            _GENESIS_NAME,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_descriptor,
        )
        try:
            os.fchmod(descriptor, 0o600)
            written = 0
            while written < len(payload):
                written += os.write(descriptor, payload[written:])
            os.fsync(descriptor)
        except BaseException:
            os.close(descriptor)
            descriptor = -1
            with suppress(FileNotFoundError):
                os.unlink(_GENESIS_NAME, dir_fd=directory_descriptor)
            raise
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        os.fsync(directory_descriptor)
        return _validate_store_genesis(target_journal_path, directory_descriptor)


def record_paper_order_decision(
    target_journal_path: str | Path,
    decision_directory: str | Path,
    decision: PaperOrderDecision,
) -> PaperOrderDecision:
    """Consume one target only through an initialized private decision store."""

    directory = Path(decision_directory)
    with (
        _private_decision_directory(directory, create=False) as directory_descriptor,
        _core._store_lock(directory_descriptor),
        _pinned_store_claim(directory) as validate_claim,
    ):
        genesis_sha256 = _validate_store_genesis(
            target_journal_path,
            directory_descriptor,
        )
        validate_claim(genesis_sha256)
        _core._replay_paper_order_decision_store_unlocked(
            target_journal_path,
            directory_descriptor,
        )
        return _core._record_paper_order_decision_unlocked(
            target_journal_path,
            directory_descriptor,
            decision,
            pre_publish_check=lambda: validate_claim(genesis_sha256),
        )


def replay_paper_order_decision_store(
    target_journal_path: str | Path,
    decision_directory: str | Path,
) -> PaperDecisionStoreReplay:
    """Replay decisions only through an initialized private decision store."""

    directory = Path(decision_directory)
    with (
        _private_decision_directory(directory, create=False) as directory_descriptor,
        _core._store_lock(directory_descriptor),
        _pinned_store_claim(directory) as validate_claim,
    ):
        genesis_sha256 = _validate_store_genesis(
            target_journal_path,
            directory_descriptor,
        )
        validate_claim(genesis_sha256)
        return _core._replay_paper_order_decision_store_unlocked(
            target_journal_path,
            directory_descriptor,
        )


def pending_target_position_intents(
    target_journal_path: str | Path,
    decision_directory: str | Path,
) -> tuple[TargetPositionIntent, ...]:
    """Return pending targets from a replay-validated private decision store."""

    return replay_paper_order_decision_store(
        target_journal_path,
        decision_directory,
    ).pending_target_intents
