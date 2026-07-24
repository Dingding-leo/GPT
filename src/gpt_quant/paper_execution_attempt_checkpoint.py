from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .execution_quote_binding_journal import ExecutionQuoteBindingJournal
from .execution_quote_evidence import ExecutionQuoteEvidenceStore
from .paper_execution_attempt import PaperExecutionAttempt
from .paper_execution_attempt_journal import (
    PaperExecutionAttemptJournal,
    _exclusive_writer_lock,
    _parse_journal_bytes,
    _publish_private_journal,
    _read_private_journal,
    _verify_reconstruction,
    load_paper_execution_attempt_journal,
    record_paper_execution_attempt_evidence,
)
from .target_intent_journal import TargetPositionIntentJournal

_SCHEMA_VERSION = 1
_HEX_64 = re.compile(r"[0-9a-f]{64}")
_CHECKPOINT_SUFFIX = ".checkpoint.json"


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate checkpoint field: {key}")
        result[key] = value
    return result


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _require_sha256(value: object, *, field: str) -> str:
    if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class PaperExecutionAttemptCheckpoint:
    schema_version: int
    sequence: int
    journal_sha256: str
    attempt_count: int
    previous_checkpoint_id: str | None
    checkpoint_id: str

    def _identity_payload(self) -> dict[str, Any]:
        return {
            "attempt_count": self.attempt_count,
            "journal_sha256": self.journal_sha256,
            "previous_checkpoint_id": self.previous_checkpoint_id,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
        }

    def to_json_bytes(self) -> bytes:
        payload = self._identity_payload()
        payload["checkpoint_id"] = self.checkpoint_id
        return _canonical_json_bytes(payload)

    @classmethod
    def from_json_bytes(cls, value: bytes) -> PaperExecutionAttemptCheckpoint:
        if not value.endswith(b"\n") or value.count(b"\n") != 1:
            raise ValueError(
                "paper execution checkpoint must be one newline-terminated JSON record"
            )
        try:
            payload = json.loads(value, object_pairs_hook=_reject_duplicate_fields)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("paper execution checkpoint must be valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("paper execution checkpoint must be a JSON object")
        expected = {
            "attempt_count",
            "checkpoint_id",
            "journal_sha256",
            "previous_checkpoint_id",
            "schema_version",
            "sequence",
        }
        if set(payload) != expected:
            raise ValueError("paper execution checkpoint fields are not canonical")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("unsupported paper execution checkpoint schema")
        sequence = payload["sequence"]
        attempt_count = payload["attempt_count"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise ValueError("checkpoint sequence must be a positive integer")
        if (
            isinstance(attempt_count, bool)
            or not isinstance(attempt_count, int)
            or attempt_count < 1
        ):
            raise ValueError("checkpoint attempt_count must be a positive integer")
        previous = payload["previous_checkpoint_id"]
        if previous is not None:
            previous = _require_sha256(previous, field="previous_checkpoint_id")
        checkpoint = cls(
            schema_version=_SCHEMA_VERSION,
            sequence=sequence,
            journal_sha256=_require_sha256(payload["journal_sha256"], field="journal_sha256"),
            attempt_count=attempt_count,
            previous_checkpoint_id=previous,
            checkpoint_id=_require_sha256(payload["checkpoint_id"], field="checkpoint_id"),
        )
        expected_id = hashlib.sha256(
            _canonical_json_bytes(checkpoint._identity_payload())
        ).hexdigest()
        if checkpoint.checkpoint_id != expected_id:
            raise ValueError("paper execution checkpoint ID does not reconstruct")
        if checkpoint.to_json_bytes() != value:
            raise ValueError("paper execution checkpoint JSON is not canonical")
        return checkpoint


def verify_paper_execution_attempt_checkpoint(
    journal: PaperExecutionAttemptJournal,
    checkpoint: PaperExecutionAttemptCheckpoint,
) -> None:
    if not isinstance(journal, PaperExecutionAttemptJournal):
        raise TypeError("journal must be a PaperExecutionAttemptJournal")
    if not isinstance(checkpoint, PaperExecutionAttemptCheckpoint):
        raise TypeError("checkpoint must be a PaperExecutionAttemptCheckpoint")
    actual_sha256 = hashlib.sha256(journal.to_bytes()).hexdigest()
    if journal.sha256 != actual_sha256:
        raise ValueError("paper execution journal SHA-256 does not match its canonical bytes")
    if checkpoint.journal_sha256 != actual_sha256 or checkpoint.attempt_count != journal.count:
        raise ValueError("paper execution journal does not match its durable checkpoint")


def advance_paper_execution_attempt_checkpoint(
    journal: PaperExecutionAttemptJournal,
    *,
    previous: PaperExecutionAttemptCheckpoint | None = None,
    previous_journal: PaperExecutionAttemptJournal | None = None,
) -> PaperExecutionAttemptCheckpoint:
    actual_sha256 = hashlib.sha256(journal.to_bytes()).hexdigest()
    if journal.sha256 != actual_sha256 or journal.count < 1:
        raise ValueError("paper execution journal must be a non-empty canonical journal")

    if previous is None:
        if previous_journal is not None:
            raise ValueError("previous_journal requires a previous checkpoint")
        sequence = 1
        previous_id = None
    else:
        if previous_journal is None:
            raise ValueError("previous checkpoint requires previous_journal evidence")
        verify_paper_execution_attempt_checkpoint(previous_journal, previous)
        previous_bytes = previous_journal.to_bytes()
        current_bytes = journal.to_bytes()
        if current_bytes == previous_bytes:
            return previous
        if not current_bytes.startswith(previous_bytes):
            raise ValueError("paper execution journal is not an append-only checkpoint extension")
        sequence = previous.sequence + 1
        previous_id = previous.checkpoint_id

    identity = {
        "attempt_count": journal.count,
        "journal_sha256": actual_sha256,
        "previous_checkpoint_id": previous_id,
        "schema_version": _SCHEMA_VERSION,
        "sequence": sequence,
    }
    checkpoint_id = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
    return PaperExecutionAttemptCheckpoint(
        schema_version=_SCHEMA_VERSION,
        sequence=sequence,
        journal_sha256=actual_sha256,
        attempt_count=journal.count,
        previous_checkpoint_id=previous_id,
        checkpoint_id=checkpoint_id,
    )


def _checkpoint_name(journal_path: Path) -> str:
    return f"{journal_path.name}{_CHECKPOINT_SUFFIX}"


def record_paper_execution_attempt_checkpoint(
    path: str | Path,
    journal: PaperExecutionAttemptJournal,
    *,
    previous_journal: PaperExecutionAttemptJournal | None = None,
) -> PaperExecutionAttemptCheckpoint:
    journal_path = Path(path)
    with _exclusive_writer_lock(journal_path) as (directory_descriptor, _):
        checkpoint_name = _checkpoint_name(journal_path)
        try:
            existing_bytes = _read_private_journal(directory_descriptor, checkpoint_name)
        except FileNotFoundError:
            previous = None
        except ValueError as exc:
            if isinstance(exc.__cause__, FileNotFoundError):
                previous = None
            else:
                raise
        else:
            previous = PaperExecutionAttemptCheckpoint.from_json_bytes(existing_bytes)

        checkpoint = advance_paper_execution_attempt_checkpoint(
            journal,
            previous=previous,
            previous_journal=previous_journal,
        )
        if previous is not None and checkpoint == previous:
            return previous
        _publish_private_journal(
            directory_descriptor,
            checkpoint_name,
            checkpoint.to_json_bytes(),
        )
        return checkpoint


def load_checkpointed_paper_execution_attempt_journal(
    path: str | Path,
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
    binding_journal: ExecutionQuoteBindingJournal,
) -> tuple[PaperExecutionAttemptJournal, PaperExecutionAttemptCheckpoint]:
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
        checkpoint = PaperExecutionAttemptCheckpoint.from_json_bytes(
            _read_private_journal(directory_descriptor, _checkpoint_name(journal_path))
        )
        verify_paper_execution_attempt_checkpoint(journal, checkpoint)
        return journal, checkpoint


def record_checkpointed_paper_execution_attempt_evidence(
    path: str | Path,
    attempt: PaperExecutionAttempt,
    *,
    intent_journal: TargetPositionIntentJournal,
    quote_store: ExecutionQuoteEvidenceStore,
    binding_journal: ExecutionQuoteBindingJournal,
) -> tuple[PaperExecutionAttemptJournal, PaperExecutionAttemptCheckpoint]:
    try:
        previous_journal = load_paper_execution_attempt_journal(
            path,
            intent_journal=intent_journal,
            quote_store=quote_store,
            binding_journal=binding_journal,
        )
    except (FileNotFoundError, ValueError) as exc:
        if isinstance(exc, FileNotFoundError) or isinstance(exc.__cause__, FileNotFoundError):
            previous_journal = None
        else:
            raise

    journal = record_paper_execution_attempt_evidence(
        path,
        attempt,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    checkpoint = record_paper_execution_attempt_checkpoint(
        path,
        journal,
        previous_journal=previous_journal,
    )
    return journal, checkpoint
