from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

__all__ = ["PaperOrderDecision"]

_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_ERROR = "paper order decision"
_FIELDS = {
    "schema_version",
    "target_intent_id",
    "instrument_id",
    "decided_at_utc",
    "market_observed_at_utc",
    "outcome",
    "reason_code",
    "order_type",
    "side",
    "base_quantity",
    "instrument_snapshot_sha256",
    "market_snapshot_sha256",
    "portfolio_state_before_sha256",
    "risk_state_before_sha256",
    "exchange_fee_bps",
    "spread_bps",
    "slippage_bps",
    "market_impact_bps",
    "latency_ms",
}
_SERIALIZED_FIELDS = _FIELDS | {"decision_id"}


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


def _decimal(value: object, name: str) -> str:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical non-negative ASCII decimal string")
    canonical = format(Decimal(value), "f")
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
            raise ValueError(f"{_ERROR} JSON contains duplicate field {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class PaperOrderDecision:
    """Immutable pre-trade paper decision, independent of persistence adapters.

    The record is provider-neutral and places no order. Filesystem journals and
    future paper brokers consume this same canonical domain object rather than
    defining a second decision schema.
    """

    target_intent_id: str
    instrument_id: str
    decided_at_utc: datetime
    market_observed_at_utc: datetime
    outcome: Literal["planned", "rejected"]
    reason_code: str
    order_type: Literal["market", "none"]
    side: Literal["buy", "sell", "none"]
    base_quantity: str
    instrument_snapshot_sha256: str
    market_snapshot_sha256: str
    portfolio_state_before_sha256: str
    risk_state_before_sha256: str
    exchange_fee_bps: str
    spread_bps: str
    slippage_bps: str
    market_impact_bps: str
    latency_ms: int
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    decision_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "target_intent_id", _digest(self.target_intent_id, "target_intent_id")
        )
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        object.__setattr__(self, "decided_at_utc", _utc(self.decided_at_utc, "decided_at_utc"))
        object.__setattr__(
            self,
            "market_observed_at_utc",
            _utc(self.market_observed_at_utc, "market_observed_at_utc"),
        )
        if self.market_observed_at_utc > self.decided_at_utc:
            raise ValueError("market observation cannot be after the decision")

        outcome = _token(self.outcome, "outcome")
        order_type = _token(self.order_type, "order_type")
        side = _token(self.side, "side")
        object.__setattr__(self, "reason_code", _token(self.reason_code, "reason_code"))
        if outcome not in {"planned", "rejected"}:
            raise ValueError("outcome must be planned or rejected")
        if order_type not in {"market", "none"} or side not in {"buy", "sell", "none"}:
            raise ValueError("invalid paper order type or side")
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "order_type", order_type)
        object.__setattr__(self, "side", side)

        quantity = _decimal(self.base_quantity, "base_quantity")
        if outcome == "planned":
            if order_type != "market" or side not in {"buy", "sell"} or Decimal(quantity) <= 0:
                raise ValueError("planned decisions require a positive market buy/sell quantity")
        elif (order_type, side, quantity) != ("none", "none", "0"):
            raise ValueError("rejected decisions require zero quantity and no order fields")
        object.__setattr__(self, "base_quantity", quantity)

        for name in (
            "instrument_snapshot_sha256",
            "market_snapshot_sha256",
            "portfolio_state_before_sha256",
            "risk_state_before_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        for name in (
            "exchange_fee_bps",
            "spread_bps",
            "slippage_bps",
            "market_impact_bps",
        ):
            object.__setattr__(self, name, _decimal(getattr(self, name), name))
        if isinstance(self.latency_ms, bool) or not isinstance(self.latency_ms, int):
            raise ValueError("latency_ms must be a non-negative integer")
        if self.latency_ms < 0:
            raise ValueError("latency_ms must be a non-negative integer")
        object.__setattr__(
            self, "decision_id", hashlib.sha256(_json_bytes(self._payload())).hexdigest()
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "target_intent_id": self.target_intent_id,
            "instrument_id": self.instrument_id,
            "decided_at_utc": _format_utc(self.decided_at_utc),
            "market_observed_at_utc": _format_utc(self.market_observed_at_utc),
            "outcome": self.outcome,
            "reason_code": self.reason_code,
            "order_type": self.order_type,
            "side": self.side,
            "base_quantity": self.base_quantity,
            "instrument_snapshot_sha256": self.instrument_snapshot_sha256,
            "market_snapshot_sha256": self.market_snapshot_sha256,
            "portfolio_state_before_sha256": self.portfolio_state_before_sha256,
            "risk_state_before_sha256": self.risk_state_before_sha256,
            "exchange_fee_bps": self.exchange_fee_bps,
            "spread_bps": self.spread_bps,
            "slippage_bps": self.slippage_bps,
            "market_impact_bps": self.market_impact_bps,
            "latency_ms": self.latency_ms,
        }

    def to_json_bytes(self) -> bytes:
        return _json_bytes({**self._payload(), "decision_id": self.decision_id}) + b"\n"

    @classmethod
    def from_json_bytes(cls, value: bytes) -> PaperOrderDecision:
        try:
            serialized = value.decode("utf-8")
            payload = json.loads(serialized, object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError(f"{_ERROR} JSON is unreadable") from exc
        if not isinstance(payload, Mapping) or set(payload) != _SERIALIZED_FIELDS:
            raise ValueError(f"{_ERROR} fields do not match schema")
        if payload["schema_version"] != _SCHEMA_VERSION:
            raise ValueError(f"unsupported {_ERROR} schema")
        decision = cls(**{name: payload[name] for name in _FIELDS - {"schema_version"}})
        if payload["decision_id"] != decision.decision_id:
            raise ValueError(f"{_ERROR} ID does not match its payload")
        if decision.to_json_bytes() != value:
            raise ValueError(f"{_ERROR} JSON must use canonical encoding")
        return decision
