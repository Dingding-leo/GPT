from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from . import _paper_decision_store_core as _core
from .execution_intent import TargetPositionIntent

PaperOrderDecision = _core.PaperOrderDecision
PaperDecisionStoreReplay = _core.PaperDecisionStoreReplay
load_paper_order_decision = _core.load_paper_order_decision

# Preserve the public import path for representation and pickle compatibility after
# splitting filesystem security from the immutable decision schema.
PaperOrderDecision.__module__ = __name__
PaperDecisionStoreReplay.__module__ = __name__

__all__ = [
    "PaperDecisionStoreReplay",
    "PaperOrderDecision",
    "load_paper_order_decision",
    "pending_target_position_intents",
    "record_paper_order_decision",
    "replay_paper_order_decision_store",
]


def _validate_private_directory(descriptor: int) -> os.stat_result:
    directory_stat = os.fstat(descriptor)
    if not stat.S_ISDIR(directory_stat.st_mode):
        raise ValueError("paper decision directory must be a regular directory")
    if hasattr(os, "geteuid") and directory_stat.st_uid != os.geteuid():
        raise ValueError("paper decision directory must be owned by the current user")
    if stat.S_IMODE(directory_stat.st_mode) & 0o022:
        raise ValueError("paper decision directory must not be group/world writable")
    return directory_stat


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
) -> Iterator[None]:
    if create or not directory.exists():
        if directory.is_symlink():
            raise ValueError("paper decision directory must not be a symbolic link")
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)

    descriptor = os.open(
        directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        opened = _validate_private_directory(descriptor)
        _assert_directory_identity(directory, opened)
        yield
        _assert_directory_identity(directory, opened)
    finally:
        os.close(descriptor)


def record_paper_order_decision(
    target_journal_path: str | Path,
    decision_directory: str | Path,
    decision: PaperOrderDecision,
) -> PaperOrderDecision:
    """Consume one target only through a validated private decision store."""

    directory = Path(decision_directory)
    with _private_decision_directory(directory, create=True):
        return _core.record_paper_order_decision(
            target_journal_path,
            directory,
            decision,
        )


def replay_paper_order_decision_store(
    target_journal_path: str | Path,
    decision_directory: str | Path,
) -> PaperDecisionStoreReplay:
    """Replay decisions only through a validated private decision store."""

    directory = Path(decision_directory)
    with _private_decision_directory(directory, create=False):
        return _core.replay_paper_order_decision_store(
            target_journal_path,
            directory,
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
