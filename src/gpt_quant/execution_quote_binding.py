from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction

from .execution_intent import TargetPositionIntent
from .execution_quote import ExecutionQuoteSnapshot

_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_DECIMAL_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_PAYLOAD_KEYS = {
    "schema_version",
    "target_intent_id",
    "quote_snapshot_id",
    "instrument_id",
    "decision_at_utc",
    "maximum_age_ms",
    "quote_observed_at_utc",
    "quote_received_at_utc",
    "instrument_snapshot_sha256",
    "observed_spread_bps",
}
_SERIALIZED_KEYS = _PAYLOAD_KEYS | {"binding_id"}


def _required_hash(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _required_utc_datetime(value: object, *, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field_name} must be a timezone-aware timestamp") from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise ValueError(f"{field_name} must be a timezone-aware timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware timestamp")
    return parsed.astimezone(UTC)


def _required_non_negative_integer(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _canonical_non_negative_decimal(value: object, *, field_name: str) -> str:
    if isinstance(value, Decimal):
        parsed = value
    elif isinstance(value, str) and _DECIMAL_PATTERN.fullmatch(value) is not None:
        parsed = Decimal(value)
    else:
        raise ValueError(f"{field_name} must be a canonical non-negative decimal")
    if not parsed.is_finite() or parsed < 0:
        raise ValueError(f"{field_name} must be a canonical non-negative decimal")
    canonical = format(parsed, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    canonical = canonical or "0"
    if isinstance(value, str) and canonical != value:
        raise ValueError(f"{field_name} must use canonical decimal encoding")
    return canonical


def _deterministic_spread_bps(quote: ExecutionQuoteSnapshot) -> str:
    """Return a context-independent 50-significant-digit spread encoding."""

    bid = Fraction(Decimal(quote.bid_price))
    ask = Fraction(Decimal(quote.ask_price))
    exact_spread_bps = (ask - bid) * 20_000 / (ask + bid)
    with localcontext(Context(prec=50, rounding=ROUND_HALF_EVEN)):
        spread_bps = Decimal(exact_spread_bps.numerator) / Decimal(
            exact_spread_bps.denominator
        )
    return _canonical_non_negative_decimal(
        spread_bps,
        field_name="observed_spread_bps",
    )


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"execution quote binding JSON contains duplicate field {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class ExecutionQuoteBinding:
    """Immutable proof that one quote was usable for one target decision instant.

    The binding is market-timing evidence only. It is not a risk approval, order,
    acceptance, rejection, fill, or permission to trade. Exchange fee, slippage,
    market impact, and later execution latency remain separate inputs.
    """

    target_intent_id: str
    quote_snapshot_id: str
    instrument_id: str
    decision_at_utc: datetime
    maximum_age_ms: int
    quote_observed_at_utc: datetime
    quote_received_at_utc: datetime
    instrument_snapshot_sha256: str
    observed_spread_bps: str
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    binding_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target_intent_id",
            _required_hash(self.target_intent_id, field_name="target_intent_id"),
        )
        object.__setattr__(
            self,
            "quote_snapshot_id",
            _required_hash(self.quote_snapshot_id, field_name="quote_snapshot_id"),
        )
        object.__setattr__(
            self,
            "instrument_id",
            _required_text(self.instrument_id, field_name="instrument_id"),
        )
        for field_name in (
            "decision_at_utc",
            "quote_observed_at_utc",
            "quote_received_at_utc",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_utc_datetime(getattr(self, field_name), field_name=field_name),
            )
        if self.quote_observed_at_utc > self.quote_received_at_utc:
            raise ValueError("quote observation cannot be after local receipt")
        if self.quote_received_at_utc >= self.decision_at_utc:
            raise ValueError("quote receipt must be strictly before the decision")
        object.__setattr__(
            self,
            "maximum_age_ms",
            _required_non_negative_integer(self.maximum_age_ms, field_name="maximum_age_ms"),
        )
        if self.decision_at_utc - self.quote_observed_at_utc > timedelta(
            milliseconds=self.maximum_age_ms
        ):
            raise ValueError("execution quote binding is stale for the configured maximum age")
        object.__setattr__(
            self,
            "instrument_snapshot_sha256",
            _required_hash(
                self.instrument_snapshot_sha256,
                field_name="instrument_snapshot_sha256",
            ),
        )
        object.__setattr__(
            self,
            "observed_spread_bps",
            _canonical_non_negative_decimal(
                self.observed_spread_bps,
                field_name="observed_spread_bps",
            ),
        )
        object.__setattr__(
            self,
            "binding_id",
            hashlib.sha256(_canonical_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target_intent_id": self.target_intent_id,
            "quote_snapshot_id": self.quote_snapshot_id,
            "instrument_id": self.instrument_id,
            "decision_at_utc": _format_utc(self.decision_at_utc),
            "maximum_age_ms": self.maximum_age_ms,
            "quote_observed_at_utc": _format_utc(self.quote_observed_at_utc),
            "quote_received_at_utc": _format_utc(self.quote_received_at_utc),
            "instrument_snapshot_sha256": self.instrument_snapshot_sha256,
            "observed_spread_bps": self.observed_spread_bps,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "binding_id": self.binding_id}

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict()) + b"\n"

    def assert_reconstructs(
        self,
        intent: TargetPositionIntent,
        quote: ExecutionQuoteSnapshot,
    ) -> None:
        """Re-run the original quote/intent validity checks and exact field binding."""

        if not isinstance(intent, TargetPositionIntent):
            raise TypeError("intent must be a TargetPositionIntent")
        if not isinstance(quote, ExecutionQuoteSnapshot):
            raise TypeError("quote must be an ExecutionQuoteSnapshot")
        if intent.intent_id != self.target_intent_id:
            raise ValueError("execution quote binding target intent does not match")
        quote.assert_usable_for(
            intent,
            decision_at_utc=self.decision_at_utc,
            maximum_age_ms=self.maximum_age_ms,
        )
        expected = bind_execution_quote(
            intent,
            quote,
            decision_at_utc=self.decision_at_utc,
            maximum_age_ms=self.maximum_age_ms,
        )
        if expected != self:
            raise ValueError("execution quote binding does not match its quote evidence")

    @classmethod
    def from_mapping(cls, value: object) -> ExecutionQuoteBinding:
        if not isinstance(value, Mapping):
            raise ValueError("execution quote binding must be a mapping")
        keys = set(value)
        if keys != _SERIALIZED_KEYS:
            missing = sorted(_SERIALIZED_KEYS - keys)
            unexpected = sorted(repr(key) for key in keys - _SERIALIZED_KEYS)
            raise ValueError(
                "execution quote binding fields do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        schema_version = value["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != _SCHEMA_VERSION
        ):
            raise ValueError(f"unsupported execution quote binding schema {schema_version!r}")
        binding = cls(
            target_intent_id=value["target_intent_id"],
            quote_snapshot_id=value["quote_snapshot_id"],
            instrument_id=value["instrument_id"],
            decision_at_utc=value["decision_at_utc"],
            maximum_age_ms=value["maximum_age_ms"],
            quote_observed_at_utc=value["quote_observed_at_utc"],
            quote_received_at_utc=value["quote_received_at_utc"],
            instrument_snapshot_sha256=value["instrument_snapshot_sha256"],
            observed_spread_bps=value["observed_spread_bps"],
        )
        if value["binding_id"] != binding.binding_id:
            raise ValueError("execution quote binding ID does not match its payload")
        return binding

    @classmethod
    def from_json_bytes(cls, value: bytes) -> ExecutionQuoteBinding:
        try:
            text = value.decode("utf-8")
            payload = json.loads(text, object_pairs_hook=_reject_duplicate_fields)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("execution quote binding JSON is unreadable") from exc
        binding = cls.from_mapping(payload)
        if binding.to_json_bytes() != value:
            raise ValueError("execution quote binding JSON must use canonical encoding")
        return binding


def bind_execution_quote(
    intent: TargetPositionIntent,
    quote: ExecutionQuoteSnapshot,
    *,
    decision_at_utc: datetime | str,
    maximum_age_ms: int,
) -> ExecutionQuoteBinding:
    """Validate and bind one immutable quote to one target decision instant."""

    if not isinstance(intent, TargetPositionIntent):
        raise TypeError("intent must be a TargetPositionIntent")
    if not isinstance(quote, ExecutionQuoteSnapshot):
        raise TypeError("quote must be an ExecutionQuoteSnapshot")
    decision_at = _required_utc_datetime(decision_at_utc, field_name="decision_at_utc")
    maximum_age = _required_non_negative_integer(maximum_age_ms, field_name="maximum_age_ms")
    quote.assert_usable_for(
        intent,
        decision_at_utc=decision_at,
        maximum_age_ms=maximum_age,
    )
    return ExecutionQuoteBinding(
        target_intent_id=intent.intent_id,
        quote_snapshot_id=quote.snapshot_id,
        instrument_id=quote.instrument_id,
        decision_at_utc=decision_at,
        maximum_age_ms=maximum_age,
        quote_observed_at_utc=quote.observed_at_utc,
        quote_received_at_utc=quote.received_at_utc,
        instrument_snapshot_sha256=quote.instrument_snapshot_sha256,
        observed_spread_bps=_deterministic_spread_bps(quote),
    )
