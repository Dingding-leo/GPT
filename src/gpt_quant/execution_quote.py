from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_DECIMAL_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_PAYLOAD_KEYS = {
    "schema_version",
    "provider",
    "instrument_id",
    "observed_at_utc",
    "received_at_utc",
    "bid_price",
    "bid_quantity",
    "ask_price",
    "ask_quantity",
    "source_response_sha256",
    "instrument_snapshot_sha256",
}
_SERIALIZED_KEYS = _PAYLOAD_KEYS | {"snapshot_id"}


class TargetIntentWindow(Protocol):
    """Minimal target-intent contract needed to validate executable market evidence."""

    instrument_id: str
    decision_not_before_utc: datetime

    def assert_active_at(self, value: datetime | str) -> None: ...


def _required_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{field_name} must not contain control characters")
    return value


def _required_token(value: object, *, field_name: str) -> str:
    parsed = _required_text(value, field_name=field_name)
    if _TOKEN_PATTERN.fullmatch(parsed) is None:
        raise ValueError(f"{field_name} must be a lowercase machine token")
    return parsed


def _required_hash(value: object, *, field_name: str) -> str:
    parsed = _required_text(value, field_name=field_name)
    if _SHA256_PATTERN.fullmatch(parsed) is None:
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return parsed


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


def _required_positive_decimal(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or _DECIMAL_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be a canonical positive ASCII decimal string")
    parsed = Decimal(value)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be positive")
    canonical = format(parsed, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical != value:
        raise ValueError(f"{field_name} must use canonical decimal encoding")
    return value


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
            raise ValueError(f"execution quote JSON contains duplicate field {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class ExecutionQuoteSnapshot:
    """Immutable provider-neutral top-of-book evidence for paper execution.

    This record is market evidence only. It is not an order, fill, slippage model, or
    permission to trade. Exchange fees, slippage, market impact, and decision latency
    remain separate inputs to a later execution decision.
    """

    provider: str
    instrument_id: str
    observed_at_utc: datetime
    received_at_utc: datetime
    bid_price: str
    bid_quantity: str
    ask_price: str
    ask_quantity: str
    source_response_sha256: str
    instrument_snapshot_sha256: str
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "provider",
            _required_token(self.provider, field_name="provider"),
        )
        object.__setattr__(
            self,
            "instrument_id",
            _required_text(self.instrument_id, field_name="instrument_id"),
        )
        for field_name in ("observed_at_utc", "received_at_utc"):
            object.__setattr__(
                self,
                field_name,
                _required_utc_datetime(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if self.observed_at_utc > self.received_at_utc:
            raise ValueError("observed_at_utc cannot be after received_at_utc")

        for field_name in ("bid_price", "bid_quantity", "ask_price", "ask_quantity"):
            object.__setattr__(
                self,
                field_name,
                _required_positive_decimal(
                    getattr(self, field_name),
                    field_name=field_name,
                ),
            )
        if Decimal(self.bid_price) >= Decimal(self.ask_price):
            raise ValueError("bid_price must be strictly less than ask_price")

        for field_name in ("source_response_sha256", "instrument_snapshot_sha256"):
            object.__setattr__(
                self,
                field_name,
                _required_hash(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "snapshot_id",
            hashlib.sha256(_canonical_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "provider": self.provider,
            "instrument_id": self.instrument_id,
            "observed_at_utc": _format_utc(self.observed_at_utc),
            "received_at_utc": _format_utc(self.received_at_utc),
            "bid_price": self.bid_price,
            "bid_quantity": self.bid_quantity,
            "ask_price": self.ask_price,
            "ask_quantity": self.ask_quantity,
            "source_response_sha256": self.source_response_sha256,
            "instrument_snapshot_sha256": self.instrument_snapshot_sha256,
        }

    @property
    def midpoint(self) -> Decimal:
        return (Decimal(self.bid_price) + Decimal(self.ask_price)) / Decimal(2)

    @property
    def spread_bps(self) -> Decimal:
        return (Decimal(self.ask_price) - Decimal(self.bid_price)) / self.midpoint * Decimal(10_000)

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "snapshot_id": self.snapshot_id}

    def to_json_bytes(self) -> bytes:
        return _canonical_json_bytes(self.to_dict()) + b"\n"

    def assert_usable_for(
        self,
        intent: TargetIntentWindow,
        *,
        decision_at_utc: datetime | str,
        maximum_age_ms: int,
    ) -> None:
        """Fail closed unless this quote is current and post-activation for one intent."""

        if isinstance(maximum_age_ms, bool) or not isinstance(maximum_age_ms, int):
            raise ValueError("maximum_age_ms must be a non-negative integer")
        if maximum_age_ms < 0:
            raise ValueError("maximum_age_ms must be a non-negative integer")
        decision_at = _required_utc_datetime(
            decision_at_utc,
            field_name="decision_at_utc",
        )
        if self.instrument_id != intent.instrument_id:
            raise ValueError("execution quote instrument does not match target intent")
        intent.assert_active_at(decision_at)
        if self.observed_at_utc < intent.decision_not_before_utc.astimezone(UTC):
            raise ValueError("execution quote predates target-intent activation")
        if self.received_at_utc >= decision_at:
            raise ValueError("execution quote must be received before the decision")
        maximum_age = timedelta(milliseconds=maximum_age_ms)
        if decision_at - self.observed_at_utc > maximum_age:
            raise ValueError("execution quote is stale for the configured maximum age")

    @classmethod
    def from_mapping(cls, value: object) -> ExecutionQuoteSnapshot:
        if not isinstance(value, Mapping):
            raise ValueError("execution quote must be a mapping")
        keys = set(value)
        if keys != _SERIALIZED_KEYS:
            missing = sorted(_SERIALIZED_KEYS - keys)
            unexpected = sorted(repr(key) for key in keys - _SERIALIZED_KEYS)
            raise ValueError(
                "execution quote fields do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        schema_version = value["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != _SCHEMA_VERSION
        ):
            raise ValueError(f"unsupported execution quote schema {schema_version!r}")
        snapshot = cls(
            provider=value["provider"],
            instrument_id=value["instrument_id"],
            observed_at_utc=value["observed_at_utc"],
            received_at_utc=value["received_at_utc"],
            bid_price=value["bid_price"],
            bid_quantity=value["bid_quantity"],
            ask_price=value["ask_price"],
            ask_quantity=value["ask_quantity"],
            source_response_sha256=value["source_response_sha256"],
            instrument_snapshot_sha256=value["instrument_snapshot_sha256"],
        )
        serialized_id = value["snapshot_id"]
        if not isinstance(serialized_id, str) or serialized_id != snapshot.snapshot_id:
            raise ValueError("execution quote ID does not match its canonical payload")
        return snapshot

    @classmethod
    def from_json_bytes(cls, value: bytes | str) -> ExecutionQuoteSnapshot:
        if isinstance(value, bytes):
            try:
                serialized = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("execution quote JSON is unreadable") from exc
        elif isinstance(value, str):
            serialized = value
        else:
            raise ValueError("execution quote JSON is unreadable")
        try:
            payload = json.loads(
                serialized,
                object_pairs_hook=_reject_duplicate_fields,
            )
        except json.JSONDecodeError as exc:
            raise ValueError("execution quote JSON is unreadable") from exc
        snapshot = cls.from_mapping(payload)
        if serialized.encode("utf-8") != snapshot.to_json_bytes():
            raise ValueError("execution quote JSON must use canonical encoding")
        return snapshot
