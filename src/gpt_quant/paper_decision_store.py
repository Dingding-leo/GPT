from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

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


def _fsync_parent_directory_entry(directory: Path) -> None:
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
        os.fsync(descriptor)
        current = os.stat(parent, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("paper decision parent changed during store creation")
    finally:
        os.close(descriptor)


def _assert_directory_identity(directory: Path, opened: os.stat_result) -> None:
    current = os.stat(directory, follow_symlinks=False)
    if not stat.S_ISDIR(current.st_mode) or (opened.st_dev, opened.st_ino) != (
        current.st_dev,
        current.st_ino,
    ):
        raise RuntimeError("paper decision directory changed during operation")


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
            raise ValueError("paper decision store genesis contains duplicate JSON fields")
        result[key] = value
    return result


def _genesis_payload(target_journal_path: str | Path) -> bytes:
    journal = load_target_position_intent_journal(target_journal_path)
    return _json_bytes(
        {
            "schema_version": 1,
            "store_kind": _GENESIS_KIND,
            "target_intent_count": journal.count,
            "target_intent_ids": [intent.intent_id for intent in journal.intents],
            "target_journal_sha256": journal.sha256,
        }
    )


def _read_private_bytes_at(
    directory_descriptor: int,
    name: str,
    *,
    label: str,
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
            min(1024 * 1024, _GENESIS_MAX_BYTES + 1 - total),
        ):
            chunks.append(chunk)
            total += len(chunk)
            if total > _GENESIS_MAX_BYTES:
                raise ValueError("paper decision store genesis exceeds the size limit")
        current = os.stat(
            name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("paper decision store genesis path changed during replay")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


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
    with _private_decision_directory(directory, create=True) as directory_descriptor:
        if _GENESIS_NAME in os.listdir(directory_descriptor):
            return _validate_store_genesis(target_journal_path, directory_descriptor)
        if os.listdir(directory_descriptor):
            raise ValueError("uninitialized paper decision directory must be empty")

        payload = _genesis_payload(target_journal_path)
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
            try:
                os.unlink(_GENESIS_NAME, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
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
    with _private_decision_directory(directory, create=False) as directory_descriptor:
        _validate_store_genesis(target_journal_path, directory_descriptor)
        return _core.record_paper_order_decision(
            target_journal_path,
            directory_descriptor,
            decision,
        )


def replay_paper_order_decision_store(
    target_journal_path: str | Path,
    decision_directory: str | Path,
) -> PaperDecisionStoreReplay:
    """Replay decisions only through an initialized private decision store."""

    directory = Path(decision_directory)
    with _private_decision_directory(directory, create=False) as directory_descriptor:
        _validate_store_genesis(target_journal_path, directory_descriptor)
        return _core.replay_paper_order_decision_store(
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
