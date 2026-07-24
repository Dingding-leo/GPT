from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from .execution_intent import TargetPositionIntent
from .execution_quote import ExecutionQuoteSnapshot
from .paper_order_decision import PaperOrderDecision

__all__ = ["PaperPostOnlyOrderIntent", "build_paper_post_only_order_intent"]

_SCHEMA_VERSION = 1
_TIME_IN_FORCE = "post_only"
_EXCHANGE_FEE_BPS = "5"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_ERROR = "paper post-only order intent"
_FIELDS = {
    "schema_version",
    "decision_id",
    "target_intent_id",
    "quote_snapshot_id",
    "instrument_snapshot_sha256",
    "instrument_id",
    "decision_at_utc",
    "created_at_utc",
    "expires_at_utc",
    "quote_observed_at_utc",
    "quote_received_at_utc",
    "maximum_quote_age_ms",
    "side",
    "base_quantity",
    "limit_price",
    "reference_bid_price",
    "reference_ask_price",
    "time_in_force",
    "exchange_fee_bps",
}
_SERIALIZED_FIELDS = _FIELDS | {"order_intent_id"}


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


def _positive_decimal(value: object, name: str) -> str:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical positive decimal")
    parsed = Decimal(value)
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{name} must be a canonical positive decimal")
    canonical = format(parsed, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical != value:
        raise ValueError(f"{name} must use canonical decimal encoding")
    return value


def _maximum_age(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("maximum_quote_age_ms must be a non-negative integer")
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


@dataclass(frozen=True, slots=True)
class PaperPostOnlyOrderIntent:
    """Immutable maker order request for an offline paper adapter.

    The intent binds one approved paper decision to one exact top-of-book snapshot.
    It does not connect to an account, submit an order, or claim a fill. A later paper
    broker must persist acknowledgement, no-fill, partial-fill, cancellation, expiry,
    and requote events against ``order_intent_id``.
    """

    decision_id: str
    target_intent_id: str
    quote_snapshot_id: str
    instrument_snapshot_sha256: str
    instrument_id: str
    decision_at_utc: datetime
    created_at_utc: datetime
    expires_at_utc: datetime
    quote_observed_at_utc: datetime
    quote_received_at_utc: datetime
    maximum_quote_age_ms: int
    side: Literal["buy", "sell"]
    base_quantity: str
    limit_price: str
    reference_bid_price: str
    reference_ask_price: str
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    time_in_force: str = field(default=_TIME_IN_FORCE, init=False)
    exchange_fee_bps: str = field(default=_EXCHANGE_FEE_BPS, init=False)
    order_intent_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "decision_id",
            "target_intent_id",
            "quote_snapshot_id",
            "instrument_snapshot_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        for name in (
            "decision_at_utc",
            "created_at_utc",
            "expires_at_utc",
            "quote_observed_at_utc",
            "quote_received_at_utc",
        ):
            object.__setattr__(self, name, _utc(getattr(self, name), name))
        if self.quote_observed_at_utc > self.quote_received_at_utc:
            raise ValueError("quote observation cannot be after local receipt")
        if self.quote_received_at_utc >= self.decision_at_utc:
            raise ValueError("quote receipt must be strictly before the paper decision")
        if self.created_at_utc <= self.decision_at_utc:
            raise ValueError("post-only order intent must be created after the paper decision")
        if self.expires_at_utc <= self.created_at_utc:
            raise ValueError("post-only order intent expiry must be after creation")

        maximum_age = _maximum_age(self.maximum_quote_age_ms)
        object.__setattr__(self, "maximum_quote_age_ms", maximum_age)
        if self.created_at_utc - self.quote_observed_at_utc > timedelta(milliseconds=maximum_age):
            raise ValueError("execution quote is stale at post-only order intent creation")

        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        for name in (
            "base_quantity",
            "limit_price",
            "reference_bid_price",
            "reference_ask_price",
        ):
            object.__setattr__(self, name, _positive_decimal(getattr(self, name), name))
        bid = Decimal(self.reference_bid_price)
        ask = Decimal(self.reference_ask_price)
        limit_price = Decimal(self.limit_price)
        if bid >= ask:
            raise ValueError("reference bid and ask must form an uncrossed book")
        if self.side == "buy" and limit_price > bid:
            raise ValueError("post-only buy limit must be at or below the reference bid")
        if self.side == "sell" and limit_price < ask:
            raise ValueError("post-only sell limit must be at or above the reference ask")

        object.__setattr__(
            self,
            "order_intent_id",
            hashlib.sha256(_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "target_intent_id": self.target_intent_id,
            "quote_snapshot_id": self.quote_snapshot_id,
            "instrument_snapshot_sha256": self.instrument_snapshot_sha256,
            "instrument_id": self.instrument_id,
            "decision_at_utc": _format_utc(self.decision_at_utc),
            "created_at_utc": _format_utc(self.created_at_utc),
            "expires_at_utc": _format_utc(self.expires_at_utc),
            "quote_observed_at_utc": _format_utc(self.quote_observed_at_utc),
            "quote_received_at_utc": _format_utc(self.quote_received_at_utc),
            "maximum_quote_age_ms": self.maximum_quote_age_ms,
            "side": self.side,
            "base_quantity": self.base_quantity,
            "limit_price": self.limit_price,
            "reference_bid_price": self.reference_bid_price,
            "reference_ask_price": self.reference_ask_price,
            "time_in_force": self.time_in_force,
            "exchange_fee_bps": self.exchange_fee_bps,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes({**self._payload(), "order_intent_id": self.order_intent_id}) + b"\n"

    def assert_reconstructs(
        self,
        decision: PaperOrderDecision,
        target: TargetPositionIntent,
        quote: ExecutionQuoteSnapshot,
    ) -> None:
        expected = build_paper_post_only_order_intent(
            decision,
            target,
            quote,
            created_at_utc=self.created_at_utc,
            expires_at_utc=self.expires_at_utc,
            maximum_quote_age_ms=self.maximum_quote_age_ms,
            limit_price=self.limit_price,
        )
        if expected != self:
            raise ValueError(f"{_ERROR} does not match its decision, target, and quote evidence")

    @classmethod
    def from_json_bytes(cls, value: bytes) -> PaperPostOnlyOrderIntent:
        try:
            text = value.decode("utf-8")
            payload = json.loads(text, object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"{_ERROR} JSON is unreadable") from exc
        if not isinstance(payload, Mapping) or set(payload) != _SERIALIZED_FIELDS:
            raise ValueError(f"{_ERROR} fields do not match schema")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError(f"unsupported {_ERROR} schema")
        if payload["time_in_force"] != _TIME_IN_FORCE:
            raise ValueError("unsupported paper order time-in-force")
        if payload["exchange_fee_bps"] != _EXCHANGE_FEE_BPS:
            raise ValueError("paper order intent exchange fee must be exactly 5 bps one-way")
        intent = cls(
            **{
                name: payload[name]
                for name in _FIELDS - {"schema_version", "time_in_force", "exchange_fee_bps"}
            }
        )
        if payload["order_intent_id"] != intent.order_intent_id:
            raise ValueError(f"{_ERROR} ID does not match its payload")
        if intent.to_json_bytes() != value:
            raise ValueError(f"{_ERROR} JSON must use canonical encoding")
        return intent


def build_paper_post_only_order_intent(
    decision: PaperOrderDecision,
    target: TargetPositionIntent,
    quote: ExecutionQuoteSnapshot,
    *,
    created_at_utc: datetime | str,
    expires_at_utc: datetime | str,
    maximum_quote_age_ms: int,
    limit_price: str,
) -> PaperPostOnlyOrderIntent:
    """Translate one approved decision into one idempotent maker paper request."""

    if not isinstance(decision, PaperOrderDecision):
        raise TypeError("decision must be a PaperOrderDecision")
    if not isinstance(target, TargetPositionIntent):
        raise TypeError("target must be a TargetPositionIntent")
    if not isinstance(quote, ExecutionQuoteSnapshot):
        raise TypeError("quote must be an ExecutionQuoteSnapshot")
    if decision.outcome != "planned" or decision.order_type != "post_only_limit":
        raise ValueError("post-only order intent requires a planned post-only limit decision")
    if decision.exchange_fee_bps != _EXCHANGE_FEE_BPS:
        raise ValueError("paper order decision exchange fee must be exactly 5 bps one-way")
    if decision.target_intent_id != target.intent_id:
        raise ValueError("paper order decision does not reference the exact target intent")
    if (
        decision.instrument_id != target.instrument_id
        or target.instrument_id != quote.instrument_id
    ):
        raise ValueError("paper order decision instrument does not match target and quote evidence")
    if decision.market_snapshot_sha256 != quote.snapshot_id:
        raise ValueError("paper order decision does not reference the exact execution quote")
    if decision.instrument_snapshot_sha256 != quote.instrument_snapshot_sha256:
        raise ValueError(
            "paper order decision instrument evidence does not match the execution quote"
        )
    if decision.market_observed_at_utc != quote.observed_at_utc:
        raise ValueError("paper order decision does not reproduce the quote observation time")
    quote.assert_usable_for(
        target,
        decision_at_utc=decision.decided_at_utc,
        maximum_age_ms=maximum_quote_age_ms,
    )

    created_at = _utc(created_at_utc, "created_at_utc")
    expires_at = _utc(expires_at_utc, "expires_at_utc")
    target.assert_active_at(decision.decided_at_utc)
    target.assert_active_at(created_at)
    if expires_at > target.expires_at_utc:
        raise ValueError("post-only order intent cannot outlive its target intent")

    return PaperPostOnlyOrderIntent(
        decision_id=decision.decision_id,
        target_intent_id=target.intent_id,
        quote_snapshot_id=quote.snapshot_id,
        instrument_snapshot_sha256=quote.instrument_snapshot_sha256,
        instrument_id=quote.instrument_id,
        decision_at_utc=decision.decided_at_utc,
        created_at_utc=created_at,
        expires_at_utc=expires_at,
        quote_observed_at_utc=quote.observed_at_utc,
        quote_received_at_utc=quote.received_at_utc,
        maximum_quote_age_ms=maximum_quote_age_ms,
        side=decision.side,
        base_quantity=decision.base_quantity,
        limit_price=limit_price,
        reference_bid_price=quote.bid_price,
        reference_ask_price=quote.ask_price,
    )
