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
from .execution_quote_binding import ExecutionQuoteBinding

_SCHEMA_VERSION = 2
_LEGACY_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_FILL_PRICE_CONVENTION = "market-vwap-at-touch-or-worse"
_FIELDS = {
    "schema_version",
    "binding_id",
    "target_intent_id",
    "quote_snapshot_id",
    "instrument_id",
    "decision_at_utc",
    "quote_observed_at_utc",
    "quote_received_at_utc",
    "maximum_age_ms",
    "submitted_at_utc",
    "outcome_at_utc",
    "side",
    "requested_base_quantity",
    "outcome",
    "filled_base_quantity",
    "average_fill_price",
    "reason_code",
    "reference_bid_price",
    "reference_ask_price",
    "fill_price_convention",
    "decision_to_submission_latency_us",
    "quote_observed_to_submission_latency_us",
    "quote_received_to_submission_latency_us",
    "submission_to_outcome_latency_us",
}
_SERIALIZED_FIELDS = _FIELDS | {"attempt_id"}
_LEGACY_FIELDS = _FIELDS - {"target_intent_id"}
_LEGACY_SERIALIZED_FIELDS = _LEGACY_FIELDS | {"attempt_id"}


def _hash(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _token(value: object, name: str) -> str:
    parsed = _text(value, name)
    if _TOKEN.fullmatch(parsed) is None:
        raise ValueError(f"{name} must be a lowercase machine token")
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


def _non_negative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _decimal(value: object, name: str) -> str:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical non-negative decimal")
    parsed = Decimal(value)
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{name} must be a canonical non-negative decimal")
    canonical = format(parsed, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if (canonical or "0") != value:
        raise ValueError(f"{name} must use canonical decimal encoding")
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
            raise ValueError(f"paper execution attempt JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _microseconds(value: timedelta) -> int:
    return value.days * 86_400_000_000 + value.seconds * 1_000_000 + value.microseconds


@dataclass(frozen=True, slots=True)
class PaperExecutionAttempt:
    """Immutable paper submission outcome bound to one quote-intent decision.

    This record places no order and claims no exchange fill. It binds a paper
    execution convention to one reconstructable quote, with explicit submission,
    outcome, quantity, fill-price, and latency evidence.
    """

    binding_id: str
    target_intent_id: str
    quote_snapshot_id: str
    instrument_id: str
    decision_at_utc: datetime
    quote_observed_at_utc: datetime
    quote_received_at_utc: datetime
    maximum_age_ms: int
    submitted_at_utc: datetime
    outcome_at_utc: datetime
    side: Literal["buy", "sell"]
    requested_base_quantity: str
    outcome: Literal["accepted", "rejected", "partial", "filled"]
    filled_base_quantity: str
    average_fill_price: str
    reason_code: str
    reference_bid_price: str
    reference_ask_price: str
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    fill_price_convention: str = field(default=_FILL_PRICE_CONVENTION, init=False)
    decision_to_submission_latency_us: int = field(init=False)
    quote_observed_to_submission_latency_us: int = field(init=False)
    quote_received_to_submission_latency_us: int = field(init=False)
    submission_to_outcome_latency_us: int = field(init=False)
    attempt_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "binding_id", _hash(self.binding_id, "binding_id"))
        object.__setattr__(
            self,
            "target_intent_id",
            _hash(self.target_intent_id, "target_intent_id"),
        )
        object.__setattr__(
            self,
            "quote_snapshot_id",
            _hash(self.quote_snapshot_id, "quote_snapshot_id"),
        )
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        for name in (
            "decision_at_utc",
            "quote_observed_at_utc",
            "quote_received_at_utc",
            "submitted_at_utc",
            "outcome_at_utc",
        ):
            object.__setattr__(self, name, _utc(getattr(self, name), name))
        if self.quote_observed_at_utc > self.quote_received_at_utc:
            raise ValueError("quote observation cannot be after local receipt")
        if self.quote_received_at_utc >= self.decision_at_utc:
            raise ValueError("quote receipt must be strictly before the decision")
        if self.submitted_at_utc <= self.decision_at_utc:
            raise ValueError("paper submission must be strictly after the decision")
        if self.outcome_at_utc <= self.submitted_at_utc:
            raise ValueError("paper outcome must be strictly after submission")

        object.__setattr__(
            self,
            "maximum_age_ms",
            _non_negative_integer(self.maximum_age_ms, "maximum_age_ms"),
        )
        if self.submitted_at_utc - self.quote_observed_at_utc > timedelta(
            milliseconds=self.maximum_age_ms
        ):
            raise ValueError("execution quote is stale at paper submission")

        side = _token(self.side, "side")
        outcome = _token(self.outcome, "outcome")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if outcome not in {"accepted", "rejected", "partial", "filled"}:
            raise ValueError("outcome must be accepted, rejected, partial, or filled")
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "reason_code", _token(self.reason_code, "reason_code"))

        for name in (
            "requested_base_quantity",
            "filled_base_quantity",
            "average_fill_price",
            "reference_bid_price",
            "reference_ask_price",
        ):
            object.__setattr__(self, name, _decimal(getattr(self, name), name))
        requested = Decimal(self.requested_base_quantity)
        filled = Decimal(self.filled_base_quantity)
        fill_price = Decimal(self.average_fill_price)
        bid = Decimal(self.reference_bid_price)
        ask = Decimal(self.reference_ask_price)
        if requested <= 0:
            raise ValueError("requested_base_quantity must be positive")
        if bid <= 0 or ask <= 0 or bid >= ask:
            raise ValueError("reference bid and ask must form a positive uncrossed book")
        if filled > requested:
            raise ValueError("filled_base_quantity cannot exceed requested_base_quantity")

        if outcome in {"accepted", "rejected"}:
            if filled != 0 or fill_price != 0:
                raise ValueError(f"{outcome} attempts cannot contain fills")
        elif outcome == "partial":
            if not 0 < filled < requested or fill_price <= 0:
                raise ValueError("partial attempts require a positive incomplete fill")
        elif filled != requested or fill_price <= 0:
            raise ValueError("filled attempts require the complete requested quantity")

        if outcome in {"partial", "filled"}:
            if side == "buy" and fill_price < ask:
                raise ValueError("buy fill price cannot improve through the reference ask")
            if side == "sell" and fill_price > bid:
                raise ValueError("sell fill price cannot improve through the reference bid")

        latency_values = {
            "decision_to_submission_latency_us": self.submitted_at_utc - self.decision_at_utc,
            "quote_observed_to_submission_latency_us": self.submitted_at_utc
            - self.quote_observed_at_utc,
            "quote_received_to_submission_latency_us": self.submitted_at_utc
            - self.quote_received_at_utc,
            "submission_to_outcome_latency_us": self.outcome_at_utc - self.submitted_at_utc,
        }
        for name, value in latency_values.items():
            object.__setattr__(self, name, _microseconds(value))
        object.__setattr__(
            self,
            "attempt_id",
            hashlib.sha256(_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "target_intent_id": self.target_intent_id,
            "quote_snapshot_id": self.quote_snapshot_id,
            "instrument_id": self.instrument_id,
            "decision_at_utc": _format_utc(self.decision_at_utc),
            "quote_observed_at_utc": _format_utc(self.quote_observed_at_utc),
            "quote_received_at_utc": _format_utc(self.quote_received_at_utc),
            "maximum_age_ms": self.maximum_age_ms,
            "submitted_at_utc": _format_utc(self.submitted_at_utc),
            "outcome_at_utc": _format_utc(self.outcome_at_utc),
            "side": self.side,
            "requested_base_quantity": self.requested_base_quantity,
            "outcome": self.outcome,
            "filled_base_quantity": self.filled_base_quantity,
            "average_fill_price": self.average_fill_price,
            "reason_code": self.reason_code,
            "reference_bid_price": self.reference_bid_price,
            "reference_ask_price": self.reference_ask_price,
            "fill_price_convention": self.fill_price_convention,
            "decision_to_submission_latency_us": self.decision_to_submission_latency_us,
            "quote_observed_to_submission_latency_us": (
                self.quote_observed_to_submission_latency_us
            ),
            "quote_received_to_submission_latency_us": (
                self.quote_received_to_submission_latency_us
            ),
            "submission_to_outcome_latency_us": self.submission_to_outcome_latency_us,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "attempt_id": self.attempt_id}

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_dict()) + b"\n"

    def assert_reconstructs(
        self,
        intent: TargetPositionIntent,
        binding: ExecutionQuoteBinding,
        quote: ExecutionQuoteSnapshot,
    ) -> None:
        if not isinstance(intent, TargetPositionIntent):
            raise TypeError("intent must be a TargetPositionIntent")
        if not isinstance(binding, ExecutionQuoteBinding):
            raise TypeError("binding must be an ExecutionQuoteBinding")
        if not isinstance(quote, ExecutionQuoteSnapshot):
            raise TypeError("quote must be an ExecutionQuoteSnapshot")
        binding.assert_reconstructs(intent, quote)
        expected = record_paper_execution_attempt(
            intent,
            binding,
            quote,
            submitted_at_utc=self.submitted_at_utc,
            outcome_at_utc=self.outcome_at_utc,
            side=self.side,
            requested_base_quantity=self.requested_base_quantity,
            outcome=self.outcome,
            filled_base_quantity=self.filled_base_quantity,
            average_fill_price=self.average_fill_price,
            reason_code=self.reason_code,
        )
        if expected != self:
            raise ValueError("paper execution attempt does not match its binding and quote")

    @classmethod
    def from_mapping(cls, value: object) -> PaperExecutionAttempt:
        if not isinstance(value, Mapping):
            raise ValueError("paper execution attempt must be a mapping")
        schema_version = value.get("schema_version")
        if isinstance(schema_version, bool) or not isinstance(schema_version, int):
            raise ValueError(f"unsupported paper execution attempt schema {schema_version!r}")
        if schema_version == _LEGACY_SCHEMA_VERSION:
            raise ValueError(
                "paper execution attempt schema 1 requires explicit evidence-bound migration"
            )
        if schema_version != _SCHEMA_VERSION:
            raise ValueError(f"unsupported paper execution attempt schema {schema_version!r}")
        keys = set(value)
        if keys != _SERIALIZED_FIELDS:
            missing = sorted(_SERIALIZED_FIELDS - keys)
            unexpected = sorted(repr(key) for key in keys - _SERIALIZED_FIELDS)
            raise ValueError(
                "paper execution attempt fields do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        if value["fill_price_convention"] != _FILL_PRICE_CONVENTION:
            raise ValueError("unsupported paper fill-price convention")
        attempt = cls(
            binding_id=value["binding_id"],
            target_intent_id=value["target_intent_id"],
            quote_snapshot_id=value["quote_snapshot_id"],
            instrument_id=value["instrument_id"],
            decision_at_utc=value["decision_at_utc"],
            quote_observed_at_utc=value["quote_observed_at_utc"],
            quote_received_at_utc=value["quote_received_at_utc"],
            maximum_age_ms=value["maximum_age_ms"],
            submitted_at_utc=value["submitted_at_utc"],
            outcome_at_utc=value["outcome_at_utc"],
            side=value["side"],
            requested_base_quantity=value["requested_base_quantity"],
            outcome=value["outcome"],
            filled_base_quantity=value["filled_base_quantity"],
            average_fill_price=value["average_fill_price"],
            reason_code=value["reason_code"],
            reference_bid_price=value["reference_bid_price"],
            reference_ask_price=value["reference_ask_price"],
        )
        for name in (
            "decision_to_submission_latency_us",
            "quote_observed_to_submission_latency_us",
            "quote_received_to_submission_latency_us",
            "submission_to_outcome_latency_us",
        ):
            if value[name] != getattr(attempt, name):
                raise ValueError(f"{name} does not match the recorded timestamps")
        if value["attempt_id"] != attempt.attempt_id:
            raise ValueError("paper execution attempt ID does not match its payload")
        return attempt

    @classmethod
    def from_json_bytes(cls, value: bytes) -> PaperExecutionAttempt:
        try:
            text = value.decode("utf-8")
            payload = json.loads(text, object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("paper execution attempt JSON is unreadable") from exc
        attempt = cls.from_mapping(payload)
        if attempt.to_json_bytes() != value:
            raise ValueError("paper execution attempt JSON must use canonical encoding")
        return attempt

    @classmethod
    def migrate_v1_json_bytes(
        cls,
        value: bytes,
        intent: TargetPositionIntent,
        binding: ExecutionQuoteBinding,
        quote: ExecutionQuoteSnapshot,
    ) -> PaperExecutionAttempt:
        """Migrate one canonical schema-v1 record using its exact lineage evidence."""

        try:
            text = value.decode("utf-8")
            payload = json.loads(text, object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("paper execution attempt JSON is unreadable") from exc
        if not isinstance(payload, Mapping):
            raise ValueError("paper execution attempt must be a mapping")
        keys = set(payload)
        if keys != _LEGACY_SERIALIZED_FIELDS:
            missing = sorted(_LEGACY_SERIALIZED_FIELDS - keys)
            unexpected = sorted(repr(key) for key in keys - _LEGACY_SERIALIZED_FIELDS)
            raise ValueError(
                "legacy paper execution attempt fields do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        if payload["schema_version"] != _LEGACY_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported legacy paper execution attempt schema {payload['schema_version']!r}"
            )
        if payload["fill_price_convention"] != _FILL_PRICE_CONVENTION:
            raise ValueError("unsupported paper fill-price convention")

        migrated = record_paper_execution_attempt(
            intent,
            binding,
            quote,
            submitted_at_utc=payload["submitted_at_utc"],
            outcome_at_utc=payload["outcome_at_utc"],
            side=payload["side"],
            requested_base_quantity=payload["requested_base_quantity"],
            outcome=payload["outcome"],
            filled_base_quantity=payload["filled_base_quantity"],
            average_fill_price=payload["average_fill_price"],
            reason_code=payload["reason_code"],
        )
        expected_payload = migrated._payload()
        expected_payload.pop("target_intent_id")
        expected_payload["schema_version"] = _LEGACY_SCHEMA_VERSION
        expected = {
            **expected_payload,
            "attempt_id": hashlib.sha256(_json_bytes(expected_payload)).hexdigest(),
        }
        if payload != expected:
            raise ValueError(
                "legacy paper execution attempt does not reconstruct from supplied evidence"
            )
        if _json_bytes(expected) + b"\n" != value:
            raise ValueError("paper execution attempt JSON must use canonical encoding")
        return migrated


def record_paper_execution_attempt(
    intent: TargetPositionIntent,
    binding: ExecutionQuoteBinding,
    quote: ExecutionQuoteSnapshot,
    *,
    submitted_at_utc: datetime | str,
    outcome_at_utc: datetime | str,
    side: Literal["buy", "sell"],
    requested_base_quantity: str,
    outcome: Literal["accepted", "rejected", "partial", "filled"],
    filled_base_quantity: str,
    average_fill_price: str,
    reason_code: str,
) -> PaperExecutionAttempt:
    """Create one auditable paper submission outcome from exact quote evidence."""

    if not isinstance(intent, TargetPositionIntent):
        raise TypeError("intent must be a TargetPositionIntent")
    if not isinstance(binding, ExecutionQuoteBinding):
        raise TypeError("binding must be an ExecutionQuoteBinding")
    if not isinstance(quote, ExecutionQuoteSnapshot):
        raise TypeError("quote must be an ExecutionQuoteSnapshot")
    binding.assert_reconstructs(intent, quote)
    intent.assert_active_at(submitted_at_utc)
    if binding.quote_snapshot_id != quote.snapshot_id:
        raise ValueError("execution quote binding does not reference the supplied quote")
    if binding.instrument_id != quote.instrument_id:
        raise ValueError("execution quote binding instrument does not match the supplied quote")
    if binding.quote_observed_at_utc != quote.observed_at_utc:
        raise ValueError(
            "execution quote binding observation time does not match the supplied quote"
        )
    if binding.quote_received_at_utc != quote.received_at_utc:
        raise ValueError("execution quote binding receipt time does not match the supplied quote")
    if binding.instrument_snapshot_sha256 != quote.instrument_snapshot_sha256:
        raise ValueError("execution quote binding instrument evidence does not match")
    return PaperExecutionAttempt(
        binding_id=binding.binding_id,
        target_intent_id=intent.intent_id,
        quote_snapshot_id=quote.snapshot_id,
        instrument_id=quote.instrument_id,
        decision_at_utc=binding.decision_at_utc,
        quote_observed_at_utc=quote.observed_at_utc,
        quote_received_at_utc=quote.received_at_utc,
        maximum_age_ms=binding.maximum_age_ms,
        submitted_at_utc=submitted_at_utc,
        outcome_at_utc=outcome_at_utc,
        side=side,
        requested_base_quantity=requested_base_quantity,
        outcome=outcome,
        filled_base_quantity=filled_base_quantity,
        average_fill_price=average_fill_price,
        reason_code=reason_code,
        reference_bid_price=quote.bid_price,
        reference_ask_price=quote.ask_price,
    )
