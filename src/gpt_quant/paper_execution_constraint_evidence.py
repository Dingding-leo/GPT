from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from .execution_quote import ExecutionQuoteSnapshot
from .okx_instruments import OKXSpotInstrumentSnapshot
from .okx_order_constraints import validate_okx_paper_execution_attempt_constraints
from .paper_execution_attempt import PaperExecutionAttempt

_SCHEMA_VERSION = 1
_EXCHANGE_FEE_BPS_ONE_WAY = "5"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_PAYLOAD_FIELDS = {
    "schema_version",
    "instrument_id",
    "instrument_snapshot_sha256",
    "quote_snapshot_id",
    "attempt_id",
    "submitted_at_utc",
    "maximum_snapshot_age_ms",
    "minimum_paper_quote_notional",
    "exchange_fee_bps_one_way",
}
_SERIALIZED_FIELDS = _PAYLOAD_FIELDS | {"evidence_id"}


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
            raise ValueError(
                f"paper execution constraint evidence JSON contains duplicate field {key!r}"
            )
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class OKXPaperExecutionConstraintEvidence:
    """Content-addressed proof of the exact offline OKX paper constraint policy.

    The record does not submit an order or claim an exchange fill. It binds one
    replayable paper attempt to exact public instrument and quote identities plus
    the caller-declared freshness and minimum-notional policy. The modeled
    exchange fee is fixed at 5 bps one-way; spread, slippage, impact, and latency
    remain separate evidence and are not added to this policy.
    """

    instrument_id: str
    instrument_snapshot_sha256: str
    quote_snapshot_id: str
    attempt_id: str
    submitted_at_utc: datetime
    maximum_snapshot_age_ms: int
    minimum_paper_quote_notional: str
    exchange_fee_bps_one_way: str = field(default=_EXCHANGE_FEE_BPS_ONE_WAY, init=False)
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    evidence_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        object.__setattr__(
            self,
            "instrument_snapshot_sha256",
            _hash(self.instrument_snapshot_sha256, "instrument_snapshot_sha256"),
        )
        object.__setattr__(
            self,
            "quote_snapshot_id",
            _hash(self.quote_snapshot_id, "quote_snapshot_id"),
        )
        object.__setattr__(self, "attempt_id", _hash(self.attempt_id, "attempt_id"))
        object.__setattr__(
            self,
            "submitted_at_utc",
            _utc(self.submitted_at_utc, "submitted_at_utc"),
        )
        object.__setattr__(
            self,
            "maximum_snapshot_age_ms",
            _non_negative_integer(self.maximum_snapshot_age_ms, "maximum_snapshot_age_ms"),
        )
        object.__setattr__(
            self,
            "minimum_paper_quote_notional",
            _positive_decimal(
                self.minimum_paper_quote_notional,
                "minimum_paper_quote_notional",
            ),
        )
        if self.exchange_fee_bps_one_way != _EXCHANGE_FEE_BPS_ONE_WAY:
            raise ValueError("exchange_fee_bps_one_way must be exactly 5")
        object.__setattr__(
            self,
            "evidence_id",
            hashlib.sha256(_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "instrument_id": self.instrument_id,
            "instrument_snapshot_sha256": self.instrument_snapshot_sha256,
            "quote_snapshot_id": self.quote_snapshot_id,
            "attempt_id": self.attempt_id,
            "submitted_at_utc": _format_utc(self.submitted_at_utc),
            "maximum_snapshot_age_ms": self.maximum_snapshot_age_ms,
            "minimum_paper_quote_notional": self.minimum_paper_quote_notional,
            "exchange_fee_bps_one_way": self.exchange_fee_bps_one_way,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "evidence_id": self.evidence_id}

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_dict()) + b"\n"

    def assert_reconstructs(
        self,
        snapshot: OKXSpotInstrumentSnapshot,
        quote: ExecutionQuoteSnapshot,
        attempt: PaperExecutionAttempt,
    ) -> None:
        if not isinstance(snapshot, OKXSpotInstrumentSnapshot):
            raise TypeError("snapshot must be an OKXSpotInstrumentSnapshot")
        if not isinstance(quote, ExecutionQuoteSnapshot):
            raise TypeError("quote must be an ExecutionQuoteSnapshot")
        if not isinstance(attempt, PaperExecutionAttempt):
            raise TypeError("attempt must be a PaperExecutionAttempt")
        if snapshot.instrument_id != self.instrument_id:
            raise ValueError("constraint evidence instrument does not match the snapshot")
        if snapshot.raw_response_sha256 != self.instrument_snapshot_sha256:
            raise ValueError("constraint evidence instrument snapshot hash does not match")
        if quote.snapshot_id != self.quote_snapshot_id:
            raise ValueError("constraint evidence quote snapshot does not match")
        if attempt.attempt_id != self.attempt_id:
            raise ValueError("constraint evidence paper attempt does not match")
        if attempt.submitted_at_utc != self.submitted_at_utc:
            raise ValueError("constraint evidence submission timestamp does not match")

        validate_okx_paper_execution_attempt_constraints(
            snapshot,
            quote,
            attempt,
            maximum_snapshot_age_ms=self.maximum_snapshot_age_ms,
            minimum_paper_quote_notional=self.minimum_paper_quote_notional,
        )
        expected = OKXPaperExecutionConstraintEvidence(
            instrument_id=snapshot.instrument_id,
            instrument_snapshot_sha256=snapshot.raw_response_sha256,
            quote_snapshot_id=quote.snapshot_id,
            attempt_id=attempt.attempt_id,
            submitted_at_utc=attempt.submitted_at_utc,
            maximum_snapshot_age_ms=self.maximum_snapshot_age_ms,
            minimum_paper_quote_notional=self.minimum_paper_quote_notional,
        )
        if expected != self:
            raise ValueError("constraint evidence does not match reconstructed policy")

    @classmethod
    def from_mapping(cls, value: object) -> OKXPaperExecutionConstraintEvidence:
        if not isinstance(value, Mapping):
            raise ValueError("paper execution constraint evidence must be a mapping")
        keys = set(value)
        if keys != _SERIALIZED_FIELDS:
            missing = sorted(_SERIALIZED_FIELDS - keys)
            unexpected = sorted(repr(key) for key in keys - _SERIALIZED_FIELDS)
            raise ValueError(
                "paper execution constraint evidence fields do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        schema_version = value["schema_version"]
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != _SCHEMA_VERSION
        ):
            raise ValueError(
                f"unsupported paper execution constraint evidence schema {schema_version!r}"
            )
        fee = value["exchange_fee_bps_one_way"]
        if fee != _EXCHANGE_FEE_BPS_ONE_WAY:
            raise ValueError("exchange_fee_bps_one_way must be exactly 5")
        evidence = cls(
            instrument_id=value["instrument_id"],
            instrument_snapshot_sha256=value["instrument_snapshot_sha256"],
            quote_snapshot_id=value["quote_snapshot_id"],
            attempt_id=value["attempt_id"],
            submitted_at_utc=value["submitted_at_utc"],
            maximum_snapshot_age_ms=value["maximum_snapshot_age_ms"],
            minimum_paper_quote_notional=value["minimum_paper_quote_notional"],
        )
        serialized_id = value["evidence_id"]
        if not isinstance(serialized_id, str) or serialized_id != evidence.evidence_id:
            raise ValueError("paper execution constraint evidence ID does not match its payload")
        return evidence

    @classmethod
    def from_json_bytes(cls, value: bytes | str) -> OKXPaperExecutionConstraintEvidence:
        if isinstance(value, bytes):
            try:
                serialized = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("paper execution constraint evidence JSON is unreadable") from exc
        elif isinstance(value, str):
            serialized = value
        else:
            raise ValueError("paper execution constraint evidence JSON is unreadable")
        try:
            payload = json.loads(serialized, object_pairs_hook=_reject_duplicates)
        except ValueError as exc:
            raise ValueError("paper execution constraint evidence JSON is unreadable") from exc
        evidence = cls.from_mapping(payload)
        if serialized.encode("utf-8") != evidence.to_json_bytes():
            raise ValueError("paper execution constraint evidence JSON must use canonical encoding")
        return evidence


def record_okx_paper_execution_constraint_evidence(
    snapshot: OKXSpotInstrumentSnapshot,
    quote: ExecutionQuoteSnapshot,
    attempt: PaperExecutionAttempt,
    *,
    maximum_snapshot_age_ms: int,
    minimum_paper_quote_notional: str,
) -> OKXPaperExecutionConstraintEvidence:
    """Validate and content-address one complete offline paper constraint decision."""

    validate_okx_paper_execution_attempt_constraints(
        snapshot,
        quote,
        attempt,
        maximum_snapshot_age_ms=maximum_snapshot_age_ms,
        minimum_paper_quote_notional=minimum_paper_quote_notional,
    )
    evidence = OKXPaperExecutionConstraintEvidence(
        instrument_id=snapshot.instrument_id,
        instrument_snapshot_sha256=snapshot.raw_response_sha256,
        quote_snapshot_id=quote.snapshot_id,
        attempt_id=attempt.attempt_id,
        submitted_at_utc=attempt.submitted_at_utc,
        maximum_snapshot_age_ms=maximum_snapshot_age_ms,
        minimum_paper_quote_notional=minimum_paper_quote_notional,
    )
    evidence.assert_reconstructs(snapshot, quote, attempt)
    return evidence
