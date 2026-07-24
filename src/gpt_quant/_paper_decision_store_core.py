from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - non-POSIX only
    _fcntl = None

from .execution_intent import TargetPositionIntent
from .paper_order_decision import PaperOrderDecision
from .target_intent_journal import load_target_position_intent_journal

_ERROR = "paper order decision"


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PaperDecisionStoreReplay:
    """Deterministic replay inventory bound to the canonical target journal."""

    decisions: tuple[PaperOrderDecision, ...]
    pending_target_intents: tuple[TargetPositionIntent, ...]
    target_journal_sha256: str
    store_sha256: str


def _validate_private_file(descriptor: int, label: str) -> os.stat_result:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_nlink != 1:
        raise ValueError(f"{label} must be a regular single-link file")
    if hasattr(os, "geteuid") and file_stat.st_uid != os.geteuid():
        raise ValueError(f"{label} must be owned by the current user")
    if stat.S_IMODE(file_stat.st_mode) != 0o600:
        raise ValueError(f"{label} must use owner-only 0600 permissions")
    return file_stat


def load_paper_order_decision(path: str | Path) -> PaperOrderDecision:
    decision_path = Path(path)
    descriptor = os.open(
        decision_path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
    )
    try:
        opened = _validate_private_file(descriptor, _ERROR)
        payload = b""
        while chunk := os.read(descriptor, 1024 * 1024):
            payload += chunk
        current = os.stat(decision_path, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError(f"{_ERROR} path changed during replay")
        return PaperOrderDecision.from_json_bytes(payload)
    finally:
        os.close(descriptor)


@contextmanager
def _decision_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_name(f".{path.name}.lock")
    descriptor = os.open(
        lock_path,
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    acquired = False
    lock_stat: os.stat_result | None = None
    try:
        os.fchmod(descriptor, 0o600)
        lock_stat = _validate_private_file(descriptor, f"{_ERROR} lock")
        if _fcntl is None:
            raise RuntimeError("paper decision locking requires POSIX advisory locks")
        try:
            _fcntl.flock(descriptor, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"{_ERROR} lock is held") from exc
        acquired = True
        yield
    finally:
        if acquired:
            current = os.stat(lock_path, follow_symlinks=False)
            if lock_stat is None or (current.st_dev, current.st_ino) != (
                lock_stat.st_dev,
                lock_stat.st_ino,
            ):
                raise RuntimeError(f"{_ERROR} lock path changed")
            lock_path.unlink()
            _fcntl.flock(descriptor, _fcntl.LOCK_UN)
        os.close(descriptor)


def _validate_decision_target(
    target: TargetPositionIntent,
    decision: PaperOrderDecision,
) -> None:
    if target.intent_id != decision.target_intent_id:
        raise ValueError(f"{_ERROR} references an unknown target intent")
    if target.instrument_id != decision.instrument_id:
        raise ValueError(f"{_ERROR} instrument does not match target intent")
    if decision.decided_at_utc < target.decision_not_before_utc:
        raise ValueError(f"{_ERROR} cannot precede target activation")
    if decision.outcome == "planned":
        target.assert_active_at(decision.decided_at_utc)
        if decision.market_observed_at_utc < target.decision_not_before_utc:
            raise ValueError("planned paper decision requires a post-activation market snapshot")


def _find_target(path: str | Path, decision: PaperOrderDecision) -> TargetPositionIntent:
    intents = load_target_position_intent_journal(path).intents
    target = next((item for item in intents if item.intent_id == decision.target_intent_id), None)
    if target is None:
        raise ValueError(f"{_ERROR} references an unknown target intent")
    _validate_decision_target(target, decision)
    return target


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode):
            raise ValueError("paper decision directory must be a regular directory")
        current = os.stat(directory, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("paper decision directory changed during publication")
        os.fsync(descriptor)
        current = os.stat(directory, follow_symlinks=False)
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise RuntimeError("paper decision directory changed during publication")
    finally:
        os.close(descriptor)


def record_paper_order_decision(
    target_journal_path: str | Path,
    decision_directory: str | Path,
    decision: PaperOrderDecision,
) -> PaperOrderDecision:
    """Atomically consume one target intent into one durable paper decision file."""

    if not isinstance(decision, PaperOrderDecision):
        raise TypeError("decision must be a PaperOrderDecision")
    directory = Path(decision_directory)
    if directory.is_symlink():
        raise ValueError("paper decision directory must not be a symbolic link")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{decision.target_intent_id}.json"
    with _decision_lock(path):
        _find_target(target_journal_path, decision)
        if path.exists():
            existing = load_paper_order_decision(path)
            if existing.to_json_bytes() != decision.to_json_bytes():
                raise ValueError(f"{_ERROR} conflicts with the consumed target intent")
            return existing

        descriptor, temporary_name = tempfile.mkstemp(prefix=".paper-decision-", dir=directory)
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            payload = decision.to_json_bytes()
            written = 0
            while written < len(payload):
                written += os.write(descriptor, payload[written:])
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, path)
            _fsync_directory(directory)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)
        replayed = load_paper_order_decision(path)
        if replayed != decision:
            raise RuntimeError(f"{_ERROR} replay differs after publication")
        return replayed


def replay_paper_order_decision_store(
    target_journal_path: str | Path,
    decision_directory: str | Path,
) -> PaperDecisionStoreReplay:
    """Replay every durable decision in target-journal order and hash the result."""

    targets = load_target_position_intent_journal(target_journal_path).intents
    target_by_id = {target.intent_id: target for target in targets}
    decisions_by_target: dict[str, PaperOrderDecision] = {}
    directory = Path(decision_directory)
    if directory.exists():
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("paper decision directory must be a regular directory")
        for path in sorted(directory.glob("*.json")):
            decision = load_paper_order_decision(path)
            target = target_by_id.get(decision.target_intent_id)
            if target is None or path.name != f"{decision.target_intent_id}.json":
                raise ValueError(f"{_ERROR} store references an unknown target intent")
            if decision.target_intent_id in decisions_by_target:
                raise ValueError(f"{_ERROR} store contains a duplicate target decision")
            _validate_decision_target(target, decision)
            decisions_by_target[decision.target_intent_id] = decision

    decisions = tuple(
        decisions_by_target[target.intent_id]
        for target in targets
        if target.intent_id in decisions_by_target
    )
    pending = tuple(target for target in targets if target.intent_id not in decisions_by_target)
    target_journal_sha256 = hashlib.sha256(
        b"".join(target.to_json_bytes() for target in targets)
    ).hexdigest()
    replay_evidence = {
        "schema_version": 1,
        "target_journal_sha256": target_journal_sha256,
        "decision_ids": [decision.decision_id for decision in decisions],
        "pending_target_intent_ids": [target.intent_id for target in pending],
    }
    store_sha256 = hashlib.sha256(_json_bytes(replay_evidence)).hexdigest()
    return PaperDecisionStoreReplay(
        decisions=decisions,
        pending_target_intents=pending,
        target_journal_sha256=target_journal_sha256,
        store_sha256=store_sha256,
    )


def pending_target_position_intents(
    target_journal_path: str | Path,
    decision_directory: str | Path,
) -> tuple[TargetPositionIntent, ...]:
    """Return target intents without a replay-validated durable paper decision file."""

    return replay_paper_order_decision_store(
        target_journal_path,
        decision_directory,
    ).pending_target_intents
