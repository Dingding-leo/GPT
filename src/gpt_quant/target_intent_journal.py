from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ._atomic_publish import publish_payloads_atomically
from .execution_intent import TargetPositionIntent

_STAGING_PREFIX = ".target-intent-journal-"
_ERROR_LABEL = "target-position intent journal"


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
        intent.decision_not_before_utc,
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
            raise ValueError(
                f"{_ERROR_LABEL} contains conflicting targets for one signal decision"
            )
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


def load_target_position_intent_journal(
    path: str | Path,
) -> TargetPositionIntentJournal:
    """Load and fully replay-verify one persisted target-position intent journal."""

    journal_path = Path(path)
    return _parse_journal_bytes(journal_path.read_bytes())


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
    if journal_path.exists():
        journal = load_target_position_intent_journal(journal_path)
        matching = next(
            (existing for existing in journal.intents if existing.intent_id == intent.intent_id),
            None,
        )
        if matching is not None:
            if matching.to_json_bytes() != intent.to_json_bytes():
                raise ValueError(f"{_ERROR_LABEL} intent ID maps to conflicting bytes")
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
    return updated
