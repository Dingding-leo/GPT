from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass

from .paper_post_only_order_intent import PaperPostOnlyOrderIntent

__all__ = ["PaperSubmissionIdentity"]

_SCHEMA_VERSION = 1
_ACTION = "initial_post_only_submission"
_ERROR = "paper submission identity"


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _submission_key(decision_id: str) -> str:
    identity_payload = {
        "schema_version": _SCHEMA_VERSION,
        "action": _ACTION,
        "decision_id": decision_id,
    }
    return hashlib.sha256(_json_bytes(identity_payload)).hexdigest()


@dataclass(frozen=True, slots=True, init=False)
class PaperSubmissionIdentity:
    """Retry-stable identity for one exact initial post-only paper intent.

    ``order_intent_id`` remains the content-addressed audit identity for exact request
    bytes, including creation and expiry timestamps. ``submission_key`` is instead
    stable for one approved decision and the explicit initial-submission action. The
    identity can only be constructed from a canonical ``PaperPostOnlyOrderIntent`` so
    arbitrary bytes cannot be pinned to an approved decision. An identical retry is
    idempotent; a changed intent under the same decision fails closed. Requotes require
    a later explicit lifecycle action and cannot masquerade as another initial request.
    """

    decision_id: str
    submission_key: str
    record_id: str
    record_sha256: str

    def __init__(self, intent: PaperPostOnlyOrderIntent) -> None:
        if not isinstance(intent, PaperPostOnlyOrderIntent):
            raise TypeError("intent must be a PaperPostOnlyOrderIntent")
        canonical_record_bytes = intent.to_json_bytes()
        object.__setattr__(self, "decision_id", intent.decision_id)
        object.__setattr__(self, "submission_key", _submission_key(intent.decision_id))
        object.__setattr__(self, "record_id", intent.order_intent_id)
        object.__setattr__(
            self,
            "record_sha256",
            hashlib.sha256(canonical_record_bytes).hexdigest(),
        )

    @classmethod
    def from_order_intent(cls, intent: PaperPostOnlyOrderIntent) -> PaperSubmissionIdentity:
        return cls(intent)

    def assert_reconstructs(self, intent: PaperPostOnlyOrderIntent) -> None:
        expected = type(self).from_order_intent(intent)
        if expected != self:
            raise ValueError(f"{_ERROR} does not reconstruct from the exact order intent")

    def assert_idempotent_retry(self, candidate: PaperSubmissionIdentity) -> None:
        if not isinstance(candidate, PaperSubmissionIdentity):
            raise TypeError("candidate must be a PaperSubmissionIdentity")
        if (
            candidate.decision_id != self.decision_id
            or candidate.submission_key != self.submission_key
        ):
            raise ValueError(f"{_ERROR} belongs to a different paper decision")
        if candidate.record_id != self.record_id or candidate.record_sha256 != self.record_sha256:
            raise ValueError(f"{_ERROR} conflicts with the initial request for this paper decision")
