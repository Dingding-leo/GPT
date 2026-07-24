from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from typing import Literal

from .paper_post_only_order_intent import PaperPostOnlyOrderIntent
from .paper_submission_identity import PaperSubmissionIdentity

__all__ = [
    "PaperOrderStateTransitionRequest",
    "advance_paper_order_transition",
    "build_initial_paper_order_transition",
]

_SCHEMA_VERSION = 1
_EXCHANGE_FEE_BPS = "5"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_ERROR = "paper order state transition request"
_EVENT_TYPES = {
    "acknowledged",
    "rejected",
    "no_fill",
    "partial_fill",
    "filled",
    "timed_out",
    "cancelled",
    "requote_requested",
}
_INITIAL_EVENT_TYPES = {"acknowledged", "rejected"}
_FILL_EVENT_TYPES = {"partial_fill", "filled"}
_TRANSITIONS = {
    "acknowledged": {"no_fill", "partial_fill", "filled", "timed_out", "cancelled"},
    "no_fill": {"no_fill", "partial_fill", "filled", "timed_out", "cancelled"},
    "partial_fill": {"no_fill", "partial_fill", "filled", "timed_out", "cancelled"},
    "timed_out": {"requote_requested"},
    "cancelled": {"requote_requested"},
    "rejected": set(),
    "filled": set(),
    "requote_requested": set(),
}
_FIELDS = {
    "schema_version",
    "decision_id",
    "submission_key",
    "order_intent_id",
    "order_intent_sha256",
    "event_type",
    "sequence",
    "previous_event_id",
    "occurred_at_utc",
    "requested_base_quantity",
    "filled_base_quantity_delta",
    "fill_price",
    "exchange_fee_bps",
    "exchange_fee_quote_delta",
    "remaining_base_quantity",
}
_SERIALIZED_FIELDS = _FIELDS | {"event_id"}

EventType = Literal[
    "acknowledged",
    "rejected",
    "no_fill",
    "partial_fill",
    "filled",
    "timed_out",
    "cancelled",
    "requote_requested",
]


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _digest(value: object, name: str) -> str:
    parsed = _text(value, name)
    if _SHA256.fullmatch(parsed) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return parsed


def _utc(value: object, name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{name} must be a timezone-aware timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    return parsed.astimezone(UTC)


def _canonical_decimal(value: Decimal) -> str:
    canonical = format(value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return canonical or "0"


def _nonnegative_decimal(value: object, name: str) -> str:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical non-negative decimal")
    parsed = Decimal(value)
    if not parsed.is_finite() or parsed < 0 or _canonical_decimal(parsed) != value:
        raise ValueError(f"{name} must be a canonical non-negative decimal")
    return value


def _positive_decimal(value: object, name: str) -> str:
    parsed = _nonnegative_decimal(value, name)
    if Decimal(parsed) <= 0:
        raise ValueError(f"{name} must be a canonical positive decimal")
    return parsed


def _sequence(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("sequence must be a non-negative integer")
    return value


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"{_ERROR} JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _fill_fee(base_quantity: Decimal, fill_price: Decimal) -> str:
    with localcontext() as context:
        context.prec = max(
            len(base_quantity.as_tuple().digits) + len(fill_price.as_tuple().digits) + 8,
            28,
        )
        fee = base_quantity * fill_price * Decimal("0.0005")
    return _canonical_decimal(fee)


@dataclass(frozen=True, slots=True)
class PaperOrderStateTransitionRequest:
    """Immutable provider-neutral request to advance one paper maker order.

    This record is a domain contract for a later durable state transaction. It performs
    no broker, account, or order operation. Each request binds the retry-stable initial
    submission identity, exact order-intent bytes, prior lifecycle event, explicit event
    sequence, and any fill delta. Fill fees are fixed at exactly 5 bps one way on filled
    notional only; spread, slippage, impact, and latency remain separate diagnostics.
    """

    decision_id: str
    submission_key: str
    order_intent_id: str
    order_intent_sha256: str
    event_type: EventType
    sequence: int
    previous_event_id: str | None
    occurred_at_utc: datetime
    requested_base_quantity: str
    filled_base_quantity_delta: str
    fill_price: str | None
    exchange_fee_quote_delta: str
    remaining_base_quantity: str
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    exchange_fee_bps: str = field(default=_EXCHANGE_FEE_BPS, init=False)
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "decision_id",
            "submission_key",
            "order_intent_id",
            "order_intent_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if self.event_type not in _EVENT_TYPES:
            raise ValueError(f"unsupported {_ERROR} event type")
        object.__setattr__(self, "sequence", _sequence(self.sequence))
        if self.previous_event_id is not None:
            object.__setattr__(
                self,
                "previous_event_id",
                _digest(self.previous_event_id, "previous_event_id"),
            )
        object.__setattr__(
            self,
            "occurred_at_utc",
            _utc(self.occurred_at_utc, "occurred_at_utc"),
        )
        object.__setattr__(
            self,
            "requested_base_quantity",
            _positive_decimal(self.requested_base_quantity, "requested_base_quantity"),
        )
        for name in (
            "filled_base_quantity_delta",
            "exchange_fee_quote_delta",
            "remaining_base_quantity",
        ):
            object.__setattr__(
                self,
                name,
                _nonnegative_decimal(getattr(self, name), name),
            )

        if self.sequence == 0 and (
            self.previous_event_id is not None or self.event_type not in _INITIAL_EVENT_TYPES
        ):
            raise ValueError("sequence zero requires an initial acknowledgement or rejection")
        if self.sequence > 0 and (
            self.previous_event_id is None or self.event_type in _INITIAL_EVENT_TYPES
        ):
            raise ValueError("non-initial lifecycle events require the exact previous event ID")

        requested = Decimal(self.requested_base_quantity)
        filled_delta = Decimal(self.filled_base_quantity_delta)
        remaining = Decimal(self.remaining_base_quantity)
        if filled_delta > requested or remaining > requested:
            raise ValueError("paper order quantities cannot exceed the requested base quantity")

        if filled_delta == 0:
            if self.fill_price is not None:
                raise ValueError("zero-fill lifecycle events must not carry a fill price")
            if self.exchange_fee_quote_delta != "0":
                raise ValueError("zero-fill lifecycle events must carry zero exchange fee")
            if self.event_type in _FILL_EVENT_TYPES:
                raise ValueError("fill lifecycle events require a positive fill quantity")
        else:
            if self.event_type not in _FILL_EVENT_TYPES:
                raise ValueError(f"{self.event_type} does not permit a fill quantity")
            canonical_price = _positive_decimal(self.fill_price, "fill_price")
            object.__setattr__(self, "fill_price", canonical_price)
            expected_fee = _fill_fee(filled_delta, Decimal(canonical_price))
            if self.exchange_fee_quote_delta != expected_fee:
                raise ValueError("exchange fee must equal exactly 5 bps of filled notional")

        if self.event_type == "partial_fill" and remaining <= 0:
            raise ValueError("partial fill must leave a positive remaining quantity")
        if self.event_type == "filled" and remaining != 0:
            raise ValueError("filled event must leave zero remaining quantity")
        if self.event_type not in _FILL_EVENT_TYPES and remaining <= 0:
            raise ValueError(f"{self.event_type} requires a positive remaining quantity")

        object.__setattr__(
            self,
            "event_id",
            hashlib.sha256(_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "submission_key": self.submission_key,
            "order_intent_id": self.order_intent_id,
            "order_intent_sha256": self.order_intent_sha256,
            "event_type": self.event_type,
            "sequence": self.sequence,
            "previous_event_id": self.previous_event_id,
            "occurred_at_utc": _format_utc(self.occurred_at_utc),
            "requested_base_quantity": self.requested_base_quantity,
            "filled_base_quantity_delta": self.filled_base_quantity_delta,
            "fill_price": self.fill_price,
            "exchange_fee_bps": self.exchange_fee_bps,
            "exchange_fee_quote_delta": self.exchange_fee_quote_delta,
            "remaining_base_quantity": self.remaining_base_quantity,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes({**self._payload(), "event_id": self.event_id}) + b"\n"

    @classmethod
    def from_json_bytes(cls, value: bytes) -> PaperOrderStateTransitionRequest:
        try:
            payload = json.loads(value.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"{_ERROR} JSON is unreadable") from exc
        if not isinstance(payload, Mapping) or set(payload) != _SERIALIZED_FIELDS:
            raise ValueError(f"{_ERROR} fields do not match schema")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError(f"unsupported {_ERROR} schema")
        if payload["exchange_fee_bps"] != _EXCHANGE_FEE_BPS:
            raise ValueError(f"{_ERROR} exchange fee must be exactly 5 bps one-way")
        request = cls(
            **{name: payload[name] for name in _FIELDS - {"schema_version", "exchange_fee_bps"}}
        )
        if payload["event_id"] != request.event_id:
            raise ValueError(f"{_ERROR} ID does not match its payload")
        if request.to_json_bytes() != value:
            raise ValueError(f"{_ERROR} JSON must use canonical encoding")
        return request

    def assert_matches_evidence(
        self,
        identity: PaperSubmissionIdentity,
        intent: PaperPostOnlyOrderIntent,
    ) -> None:
        if not isinstance(identity, PaperSubmissionIdentity):
            raise TypeError("identity must be a PaperSubmissionIdentity")
        if not isinstance(intent, PaperPostOnlyOrderIntent):
            raise TypeError("intent must be a PaperPostOnlyOrderIntent")
        identity.assert_reconstructs(intent)
        if (
            self.decision_id != identity.decision_id
            or self.submission_key != identity.submission_key
            or self.order_intent_id != identity.record_id
            or self.order_intent_sha256 != identity.record_sha256
            or self.requested_base_quantity != intent.base_quantity
        ):
            raise ValueError(f"{_ERROR} does not bind the exact maker submission evidence")

    def assert_reconstructs(
        self,
        identity: PaperSubmissionIdentity,
        intent: PaperPostOnlyOrderIntent,
        *,
        previous: PaperOrderStateTransitionRequest | None = None,
    ) -> None:
        if previous is None:
            expected = build_initial_paper_order_transition(
                identity,
                intent,
                event_type=self.event_type,
                occurred_at_utc=self.occurred_at_utc,
            )
        else:
            expected = advance_paper_order_transition(
                previous,
                identity,
                intent,
                event_type=self.event_type,
                occurred_at_utc=self.occurred_at_utc,
                filled_base_quantity_delta=self.filled_base_quantity_delta,
                fill_price=self.fill_price,
            )
        if expected != self:
            raise ValueError(f"{_ERROR} does not reconstruct from its exact evidence")

    def assert_idempotent_retry(self, candidate: PaperOrderStateTransitionRequest) -> None:
        if not isinstance(candidate, PaperOrderStateTransitionRequest):
            raise TypeError("candidate must be a PaperOrderStateTransitionRequest")
        if candidate == self:
            return
        if (
            candidate.submission_key != self.submission_key
            or candidate.order_intent_id != self.order_intent_id
        ):
            raise ValueError(f"{_ERROR} belongs to a different maker order")
        if (
            candidate.sequence == self.sequence
            and candidate.previous_event_id == self.previous_event_id
        ):
            raise ValueError(f"{_ERROR} conflicts with the existing lifecycle action")
        raise ValueError(f"{_ERROR} is not an idempotent retry of this lifecycle action")


def build_initial_paper_order_transition(
    identity: PaperSubmissionIdentity,
    intent: PaperPostOnlyOrderIntent,
    *,
    event_type: Literal["acknowledged", "rejected"],
    occurred_at_utc: datetime | str,
) -> PaperOrderStateTransitionRequest:
    """Build the first immutable acknowledgement or rejection for one maker intent."""

    if not isinstance(identity, PaperSubmissionIdentity):
        raise TypeError("identity must be a PaperSubmissionIdentity")
    if not isinstance(intent, PaperPostOnlyOrderIntent):
        raise TypeError("intent must be a PaperPostOnlyOrderIntent")
    identity.assert_reconstructs(intent)
    if event_type not in _INITIAL_EVENT_TYPES:
        raise ValueError("initial lifecycle event must be acknowledged or rejected")
    occurred_at = _utc(occurred_at_utc, "occurred_at_utc")
    if occurred_at < intent.created_at_utc or occurred_at >= intent.expires_at_utc:
        raise ValueError("initial lifecycle event must occur during the exclusive intent lifetime")
    return PaperOrderStateTransitionRequest(
        decision_id=identity.decision_id,
        submission_key=identity.submission_key,
        order_intent_id=identity.record_id,
        order_intent_sha256=identity.record_sha256,
        event_type=event_type,
        sequence=0,
        previous_event_id=None,
        occurred_at_utc=occurred_at,
        requested_base_quantity=intent.base_quantity,
        filled_base_quantity_delta="0",
        fill_price=None,
        exchange_fee_quote_delta="0",
        remaining_base_quantity=intent.base_quantity,
    )


def advance_paper_order_transition(
    previous: PaperOrderStateTransitionRequest,
    identity: PaperSubmissionIdentity,
    intent: PaperPostOnlyOrderIntent,
    *,
    event_type: EventType,
    occurred_at_utc: datetime | str,
    filled_base_quantity_delta: str = "0",
    fill_price: str | None = None,
) -> PaperOrderStateTransitionRequest:
    """Build the next explicit lifecycle action for one exact maker submission."""

    if not isinstance(previous, PaperOrderStateTransitionRequest):
        raise TypeError("previous must be a PaperOrderStateTransitionRequest")
    previous.assert_matches_evidence(identity, intent)
    if event_type not in _EVENT_TYPES:
        raise ValueError(f"unsupported {_ERROR} event type")
    if event_type not in _TRANSITIONS[previous.event_type]:
        raise ValueError(f"cannot transition from {previous.event_type} to {event_type}")

    occurred_at = _utc(occurred_at_utc, "occurred_at_utc")
    if occurred_at <= previous.occurred_at_utc:
        raise ValueError("lifecycle event time must be strictly after the previous event")
    if (
        event_type in {"no_fill", "partial_fill", "filled", "cancelled"}
        and occurred_at >= intent.expires_at_utc
    ):
        raise ValueError(f"{event_type} must occur before the exclusive intent expiry")
    if event_type == "timed_out" and occurred_at < intent.expires_at_utc:
        raise ValueError("timed_out cannot occur before the exclusive intent expiry")

    canonical_delta = _nonnegative_decimal(
        filled_base_quantity_delta,
        "filled_base_quantity_delta",
    )
    delta = Decimal(canonical_delta)
    previous_remaining = Decimal(previous.remaining_base_quantity)
    if delta > previous_remaining:
        raise ValueError("fill quantity exceeds the remaining maker order quantity")
    if event_type == "partial_fill" and (delta <= 0 or delta >= previous_remaining):
        raise ValueError("partial fill quantity must be positive and below the remaining quantity")
    if event_type == "filled" and delta != previous_remaining:
        raise ValueError("filled event must consume the exact remaining quantity")
    if event_type not in _FILL_EVENT_TYPES and delta != 0:
        raise ValueError(f"{event_type} does not permit a fill quantity")
    if event_type == "requote_requested" and previous_remaining <= 0:
        raise ValueError("requote requires a positive unfilled maker quantity")

    remaining = previous_remaining - delta
    canonical_remaining = _canonical_decimal(remaining)
    canonical_price: str | None = None
    fee = "0"
    if delta > 0:
        canonical_price = _positive_decimal(fill_price, "fill_price")
        fee = _fill_fee(delta, Decimal(canonical_price))
    elif fill_price is not None:
        raise ValueError("zero-fill lifecycle events must not carry a fill price")

    return PaperOrderStateTransitionRequest(
        decision_id=identity.decision_id,
        submission_key=identity.submission_key,
        order_intent_id=identity.record_id,
        order_intent_sha256=identity.record_sha256,
        event_type=event_type,
        sequence=previous.sequence + 1,
        previous_event_id=previous.event_id,
        occurred_at_utc=occurred_at,
        requested_base_quantity=previous.requested_base_quantity,
        filled_base_quantity_delta=canonical_delta,
        fill_price=canonical_price,
        exchange_fee_quote_delta=fee,
        remaining_base_quantity=canonical_remaining,
    )
