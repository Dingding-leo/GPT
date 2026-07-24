from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal, Inexact, Rounded, localcontext
from typing import Literal

from .paper_execution_attempt import PaperExecutionAttempt

__all__ = [
    "PaperExecutionRiskImpact",
    "measure_paper_execution_risk",
]

_SCHEMA_VERSION = 1
_EXCHANGE_FEE_ONE_WAY_BPS = 5
_EXCHANGE_FEE_RATE = Decimal("0.0005")
_ONE_PLUS_EXCHANGE_FEE_RATE = Decimal("1.0005")
_RESERVATION_ASSUMPTION = "accepted-or-partial-unfilled-remains-open"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")
_DECIMAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_FIELDS = {
    "schema_version",
    "attempt_id",
    "instrument_id",
    "side",
    "outcome",
    "requested_base_quantity",
    "filled_base_quantity",
    "average_fill_price",
    "reference_bid_price",
    "reference_ask_price",
    "exchange_fee_one_way_bps",
    "reservation_assumption",
    "unfilled_base_quantity",
    "realized_quote_notional",
    "realized_exchange_fee_quote",
    "realized_cash_delta_quote",
    "position_delta_base",
    "pending_cash_reservation_quote",
    "pending_base_reservation",
    "total_buy_cash_commitment_quote",
}
_SERIALIZED_FIELDS = _FIELDS | {"risk_impact_id"}


def _digest(value: object, name: str) -> str:
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


def _decimal(value: object, name: str, *, non_negative: bool = False) -> str:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        qualifier = "non-negative " if non_negative else ""
        raise ValueError(f"{name} must be a canonical {qualifier}decimal")
    parsed = Decimal(value)
    if not parsed.is_finite() or (non_negative and parsed < 0):
        qualifier = "non-negative " if non_negative else ""
        raise ValueError(f"{name} must be a canonical {qualifier}decimal")
    if _canonical_decimal(parsed) != value:
        raise ValueError(f"{name} must use canonical decimal encoding")
    return value


def _canonical_decimal(value: Decimal) -> str:
    if value == 0:
        return "0"
    canonical = format(value, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    return canonical


def _exact_arithmetic_precision(*values: Decimal) -> int:
    coefficient_digits = sum(max(1, len(value.as_tuple().digits)) for value in values)
    maximum_scale = max(
        (max(0, -value.as_tuple().exponent) for value in values),
        default=0,
    )
    return max(64, coefficient_digits + maximum_scale + 16)


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
            raise ValueError(f"paper execution risk JSON contains duplicate field {key!r}")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class PaperExecutionRiskImpact:
    """Deterministic cash, fee, position, and pending-reservation impact.

    ``accepted`` and ``partial`` outcomes are treated conservatively: every
    unfilled quantity remains open until a later immutable terminal event proves
    cancellation, rejection, or completion. This record performs no account or
    order operation.
    """

    attempt_id: str
    instrument_id: str
    side: Literal["buy", "sell"]
    outcome: Literal["accepted", "rejected", "partial", "filled"]
    requested_base_quantity: str
    filled_base_quantity: str
    average_fill_price: str
    reference_bid_price: str
    reference_ask_price: str
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    exchange_fee_one_way_bps: int = field(default=_EXCHANGE_FEE_ONE_WAY_BPS, init=False)
    reservation_assumption: str = field(default=_RESERVATION_ASSUMPTION, init=False)
    unfilled_base_quantity: str = field(init=False)
    realized_quote_notional: str = field(init=False)
    realized_exchange_fee_quote: str = field(init=False)
    realized_cash_delta_quote: str = field(init=False)
    position_delta_base: str = field(init=False)
    pending_cash_reservation_quote: str = field(init=False)
    pending_base_reservation: str = field(init=False)
    total_buy_cash_commitment_quote: str = field(init=False)
    risk_impact_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _digest(self.attempt_id, "attempt_id"))
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))

        side = _token(self.side, "side")
        outcome = _token(self.outcome, "outcome")
        if side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if outcome not in {"accepted", "rejected", "partial", "filled"}:
            raise ValueError("outcome must be accepted, rejected, partial, or filled")
        object.__setattr__(self, "side", side)
        object.__setattr__(self, "outcome", outcome)

        for name in (
            "requested_base_quantity",
            "filled_base_quantity",
            "average_fill_price",
            "reference_bid_price",
            "reference_ask_price",
        ):
            object.__setattr__(
                self,
                name,
                _decimal(getattr(self, name), name, non_negative=True),
            )

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
                raise ValueError(f"{outcome} risk impact cannot contain fills")
        elif outcome == "partial":
            if not 0 < filled < requested or fill_price <= 0:
                raise ValueError("partial risk impact requires a positive incomplete fill")
        elif filled != requested or fill_price <= 0:
            raise ValueError("filled risk impact requires the complete requested quantity")

        if outcome in {"partial", "filled"}:
            if side == "buy" and fill_price < ask:
                raise ValueError("buy fill price cannot improve through the reference ask")
            if side == "sell" and fill_price > bid:
                raise ValueError("sell fill price cannot improve through the reference bid")

        with localcontext() as context:
            context.prec = _exact_arithmetic_precision(
                requested,
                filled,
                fill_price,
                bid,
                ask,
                _EXCHANGE_FEE_RATE,
                _ONE_PLUS_EXCHANGE_FEE_RATE,
            )
            context.traps[Inexact] = True
            context.traps[Rounded] = True

            unfilled = requested - filled
            realized_notional = filled * fill_price
            realized_fee = realized_notional * _EXCHANGE_FEE_RATE
            position_delta = filled if side == "buy" else -filled
            realized_cash_delta = (
                -(realized_notional + realized_fee)
                if side == "buy"
                else realized_notional - realized_fee
            )

            pending_cash = Decimal("0")
            pending_base = Decimal("0")
            if outcome in {"accepted", "partial"}:
                if side == "buy":
                    pending_notional = unfilled * ask
                    pending_cash = pending_notional * _ONE_PLUS_EXCHANGE_FEE_RATE
                else:
                    pending_base = unfilled

            total_buy_commitment = (
                -realized_cash_delta + pending_cash if side == "buy" else Decimal("0")
            )
        derived = {
            "unfilled_base_quantity": unfilled,
            "realized_quote_notional": realized_notional,
            "realized_exchange_fee_quote": realized_fee,
            "realized_cash_delta_quote": realized_cash_delta,
            "position_delta_base": position_delta,
            "pending_cash_reservation_quote": pending_cash,
            "pending_base_reservation": pending_base,
            "total_buy_cash_commitment_quote": total_buy_commitment,
        }
        for name, value in derived.items():
            object.__setattr__(self, name, _canonical_decimal(value))

        object.__setattr__(
            self,
            "risk_impact_id",
            hashlib.sha256(_json_bytes(self._payload())).hexdigest(),
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "attempt_id": self.attempt_id,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "outcome": self.outcome,
            "requested_base_quantity": self.requested_base_quantity,
            "filled_base_quantity": self.filled_base_quantity,
            "average_fill_price": self.average_fill_price,
            "reference_bid_price": self.reference_bid_price,
            "reference_ask_price": self.reference_ask_price,
            "exchange_fee_one_way_bps": self.exchange_fee_one_way_bps,
            "reservation_assumption": self.reservation_assumption,
            "unfilled_base_quantity": self.unfilled_base_quantity,
            "realized_quote_notional": self.realized_quote_notional,
            "realized_exchange_fee_quote": self.realized_exchange_fee_quote,
            "realized_cash_delta_quote": self.realized_cash_delta_quote,
            "position_delta_base": self.position_delta_base,
            "pending_cash_reservation_quote": self.pending_cash_reservation_quote,
            "pending_base_reservation": self.pending_base_reservation,
            "total_buy_cash_commitment_quote": self.total_buy_cash_commitment_quote,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "risk_impact_id": self.risk_impact_id}

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_dict()) + b"\n"

    def assert_reconstructs(self, attempt: PaperExecutionAttempt) -> None:
        if not isinstance(attempt, PaperExecutionAttempt):
            raise TypeError("attempt must be a PaperExecutionAttempt")
        if measure_paper_execution_risk(attempt) != self:
            raise ValueError("paper execution risk impact does not match its attempt")

    @classmethod
    def from_mapping(cls, value: object) -> PaperExecutionRiskImpact:
        if not isinstance(value, Mapping):
            raise ValueError("paper execution risk impact must be a mapping")
        keys = set(value)
        if keys != _SERIALIZED_FIELDS:
            missing = sorted(_SERIALIZED_FIELDS - keys)
            unexpected = sorted(repr(key) for key in keys - _SERIALIZED_FIELDS)
            raise ValueError(
                "paper execution risk fields do not match schema; "
                f"missing={missing}, unexpected={unexpected}"
            )
        if value["schema_version"] != _SCHEMA_VERSION:
            raise ValueError("unsupported paper execution risk schema")
        if value["exchange_fee_one_way_bps"] != _EXCHANGE_FEE_ONE_WAY_BPS:
            raise ValueError("paper execution risk must use exactly 5 bps one-way fee")
        if value["reservation_assumption"] != _RESERVATION_ASSUMPTION:
            raise ValueError("unsupported paper execution reservation assumption")

        impact = cls(
            attempt_id=value["attempt_id"],
            instrument_id=value["instrument_id"],
            side=value["side"],
            outcome=value["outcome"],
            requested_base_quantity=value["requested_base_quantity"],
            filled_base_quantity=value["filled_base_quantity"],
            average_fill_price=value["average_fill_price"],
            reference_bid_price=value["reference_bid_price"],
            reference_ask_price=value["reference_ask_price"],
        )
        for name in _FIELDS - {
            "schema_version",
            "attempt_id",
            "instrument_id",
            "side",
            "outcome",
            "requested_base_quantity",
            "filled_base_quantity",
            "average_fill_price",
            "reference_bid_price",
            "reference_ask_price",
            "exchange_fee_one_way_bps",
            "reservation_assumption",
        }:
            if value[name] != getattr(impact, name):
                raise ValueError(f"{name} does not match the paper execution attempt")
        if value["risk_impact_id"] != impact.risk_impact_id:
            raise ValueError("paper execution risk impact ID does not match its payload")
        return impact

    @classmethod
    def from_json_bytes(cls, value: bytes) -> PaperExecutionRiskImpact:
        try:
            payload = json.loads(value.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("paper execution risk JSON is unreadable") from exc
        return cls.from_mapping(payload)


def measure_paper_execution_risk(attempt: PaperExecutionAttempt) -> PaperExecutionRiskImpact:
    if not isinstance(attempt, PaperExecutionAttempt):
        raise TypeError("attempt must be a PaperExecutionAttempt")
    return PaperExecutionRiskImpact(
        attempt_id=attempt.attempt_id,
        instrument_id=attempt.instrument_id,
        side=attempt.side,
        outcome=attempt.outcome,
        requested_base_quantity=attempt.requested_base_quantity,
        filled_base_quantity=attempt.filled_base_quantity,
        average_fill_price=attempt.average_fill_price,
        reference_bid_price=attempt.reference_bid_price,
        reference_ask_price=attempt.reference_ask_price,
    )
