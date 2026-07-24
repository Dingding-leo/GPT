from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")
_RESPONSE_FIELDS = {"code", "data", "msg"}
_TRADE_FIELDS = {"instId", "px", "side", "source", "sz", "tradeId", "ts"}
_EXCHANGE_FEE_ONE_WAY_BPS = Decimal("5")


def _reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"OKX trade JSON contains duplicate field {key!r}")
        result[key] = value
    return result


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise ValueError(f"{name} must be a non-empty trimmed string")
    if any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} must not contain control characters")
    return value


def _decimal_text(value: object, name: str, *, positive: bool = False) -> str:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical non-negative decimal")
    parsed = Decimal(value)
    canonical = _format_decimal(parsed)
    if canonical != value:
        raise ValueError(f"{name} must use canonical decimal encoding")
    if positive and parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def _format_decimal(value: Decimal) -> str:
    if not value.is_finite() or value < 0:
        raise ValueError("decimal value must be finite and non-negative")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _utc(value: datetime | str, name: str) -> datetime:
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


def _format_utc(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class OKXPublicTrade:
    instrument_id: str
    trade_id: str
    price: str
    base_quantity: str
    taker_side: Literal["buy", "sell"]
    source: Literal["0", "1"]
    exchange_timestamp_ms: int
    observed_at_utc: datetime = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        object.__setattr__(self, "trade_id", _text(self.trade_id, "trade_id"))
        if not self.trade_id.isdigit():
            raise ValueError("trade_id must contain decimal digits only")
        object.__setattr__(self, "price", _decimal_text(self.price, "price", positive=True))
        object.__setattr__(
            self,
            "base_quantity",
            _decimal_text(self.base_quantity, "base_quantity", positive=True),
        )
        if self.taker_side not in {"buy", "sell"}:
            raise ValueError("taker_side must be buy or sell")
        if self.source not in {"0", "1"}:
            raise ValueError("source must be 0 or 1")
        if (
            isinstance(self.exchange_timestamp_ms, bool)
            or not isinstance(self.exchange_timestamp_ms, int)
            or self.exchange_timestamp_ms <= 0
        ):
            raise ValueError("exchange_timestamp_ms must be a positive integer")
        object.__setattr__(
            self,
            "observed_at_utc",
            datetime.fromtimestamp(self.exchange_timestamp_ms / 1000, tz=UTC),
        )


@dataclass(frozen=True, slots=True)
class OKXPublicTradeSnapshot:
    source_sha256: str
    instrument_id: str
    trades: tuple[OKXPublicTrade, ...]
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        if _SHA256.fullmatch(self.source_sha256) is None:
            raise ValueError("source_sha256 must be a lowercase SHA-256 digest")
        object.__setattr__(self, "instrument_id", _text(self.instrument_id, "instrument_id"))
        if not self.trades:
            raise ValueError("trade snapshot must contain at least one trade")
        if any(trade.instrument_id != self.instrument_id for trade in self.trades):
            raise ValueError("all trades must match the snapshot instrument")
        ordered = tuple(
            sorted(
                self.trades,
                key=lambda trade: (trade.exchange_timestamp_ms, int(trade.trade_id)),
            )
        )
        if len({trade.trade_id for trade in ordered}) != len(ordered):
            raise ValueError("trade snapshot contains duplicate trade IDs")
        object.__setattr__(self, "trades", ordered)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "source_sha256": self.source_sha256,
            "instrument_id": self.instrument_id,
            "trades": [
                {
                    "trade_id": trade.trade_id,
                    "price": trade.price,
                    "base_quantity": trade.base_quantity,
                    "taker_side": trade.taker_side,
                    "source": trade.source,
                    "exchange_timestamp_ms": trade.exchange_timestamp_ms,
                }
                for trade in ordered
            ],
        }
        object.__setattr__(self, "snapshot_id", hashlib.sha256(_json_bytes(payload)).hexdigest())

    @classmethod
    def from_json_bytes(cls, value: bytes) -> OKXPublicTradeSnapshot:
        source_sha256 = hashlib.sha256(value).hexdigest()
        try:
            payload = json.loads(value.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("OKX trade JSON is unreadable") from exc
        if not isinstance(payload, Mapping) or set(payload) != _RESPONSE_FIELDS:
            raise ValueError("OKX trade response fields do not match the public schema")
        if payload["code"] != "0" or payload["msg"] != "":
            raise ValueError("OKX trade response did not succeed cleanly")
        rows = payload["data"]
        if not isinstance(rows, list) or not rows:
            raise ValueError("OKX trade response data must be a non-empty list")
        trades: list[OKXPublicTrade] = []
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != _TRADE_FIELDS:
                raise ValueError("OKX public trade fields do not match the documented schema")
            timestamp = row["ts"]
            if not isinstance(timestamp, str) or not timestamp.isdigit():
                raise ValueError("trade ts must contain Unix milliseconds as decimal digits")
            trades.append(
                OKXPublicTrade(
                    instrument_id=row["instId"],
                    trade_id=row["tradeId"],
                    price=row["px"],
                    base_quantity=row["sz"],
                    taker_side=row["side"],
                    source=row["source"],
                    exchange_timestamp_ms=int(timestamp),
                )
            )
        instrument_ids = {trade.instrument_id for trade in trades}
        if len(instrument_ids) != 1:
            raise ValueError("OKX trade response mixes instruments")
        return cls(
            source_sha256=source_sha256,
            instrument_id=instrument_ids.pop(),
            trades=tuple(trades),
        )


@dataclass(frozen=True, slots=True)
class MakerFillReplay:
    order_intent_id: str
    trade_snapshot_id: str
    trade_source_sha256: str
    instrument_id: str
    side: Literal["buy", "sell"]
    signal_at_utc: datetime
    submitted_at_utc: datetime
    expires_at_utc: datetime
    limit_price: str
    requested_base_quantity: str
    queue_ahead_base_quantity: str
    outcome: Literal["filled", "cancelled_partial", "cancelled_no_fill"]
    filled_base_quantity: str
    unfilled_base_quantity: str
    average_fill_price: str
    exchange_fee_one_way_bps: str
    exchange_fee_quote: str
    touch_trade_count: int
    touch_base_quantity: str
    trade_through_trade_count: int
    trade_through_base_quantity: str
    queue_consumed_base_quantity: str
    remaining_queue_ahead_base_quantity: str
    first_trade_through_at_utc: datetime | None
    filled_at_utc: datetime | None
    cancelled_at_utc: datetime | None
    requote_eligible: bool
    schema_version: int = field(default=_SCHEMA_VERSION, init=False)
    replay_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("order_intent_id", "trade_snapshot_id", "trade_source_sha256"):
            value = getattr(self, name)
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        payload = self.to_dict(include_replay_id=False)
        object.__setattr__(self, "replay_id", hashlib.sha256(_json_bytes(payload)).hexdigest())

    def to_dict(self, *, include_replay_id: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": self.schema_version,
            "order_intent_id": self.order_intent_id,
            "trade_snapshot_id": self.trade_snapshot_id,
            "trade_source_sha256": self.trade_source_sha256,
            "instrument_id": self.instrument_id,
            "side": self.side,
            "signal_at_utc": _format_utc(self.signal_at_utc),
            "submitted_at_utc": _format_utc(self.submitted_at_utc),
            "expires_at_utc": _format_utc(self.expires_at_utc),
            "limit_price": self.limit_price,
            "requested_base_quantity": self.requested_base_quantity,
            "queue_ahead_base_quantity": self.queue_ahead_base_quantity,
            "outcome": self.outcome,
            "filled_base_quantity": self.filled_base_quantity,
            "unfilled_base_quantity": self.unfilled_base_quantity,
            "average_fill_price": self.average_fill_price,
            "exchange_fee_one_way_bps": self.exchange_fee_one_way_bps,
            "exchange_fee_quote": self.exchange_fee_quote,
            "touch_trade_count": self.touch_trade_count,
            "touch_base_quantity": self.touch_base_quantity,
            "trade_through_trade_count": self.trade_through_trade_count,
            "trade_through_base_quantity": self.trade_through_base_quantity,
            "queue_consumed_base_quantity": self.queue_consumed_base_quantity,
            "remaining_queue_ahead_base_quantity": self.remaining_queue_ahead_base_quantity,
            "first_trade_through_at_utc": (
                _format_utc(self.first_trade_through_at_utc)
                if self.first_trade_through_at_utc is not None
                else None
            ),
            "filled_at_utc": (
                _format_utc(self.filled_at_utc) if self.filled_at_utc is not None else None
            ),
            "cancelled_at_utc": (
                _format_utc(self.cancelled_at_utc) if self.cancelled_at_utc is not None else None
            ),
            "requote_eligible": self.requote_eligible,
        }
        if include_replay_id:
            payload["replay_id"] = self.replay_id
        return payload

    def to_json_bytes(self) -> bytes:
        return _json_bytes(self.to_dict()) + b"\n"


def simulate_post_only_maker_fill(
    snapshot: OKXPublicTradeSnapshot,
    *,
    order_intent_id: str,
    signal_at_utc: datetime | str,
    submitted_at_utc: datetime | str,
    expires_at_utc: datetime | str,
    side: Literal["buy", "sell"],
    limit_price: str,
    requested_base_quantity: str,
    queue_ahead_base_quantity: str,
) -> MakerFillReplay:
    """Replay one post-only maker order from immutable public trade evidence.

    OKX public trade ``side`` is the taker side. A price touch is diagnostic only.
    A resting buy fills only after a taker sell trades strictly below its limit;
    a resting sell fills only after a taker buy trades strictly above its limit.
    Trade-through size first consumes the declared queue ahead, then the order.
    Unfilled quantity is cancelled at the exclusive expiry and becomes requote-eligible.
    """

    if not isinstance(snapshot, OKXPublicTradeSnapshot):
        raise TypeError("snapshot must be an OKXPublicTradeSnapshot")
    if not isinstance(order_intent_id, str) or _SHA256.fullmatch(order_intent_id) is None:
        raise ValueError("order_intent_id must be a lowercase SHA-256 digest")
    signal = _utc(signal_at_utc, "signal_at_utc")
    submitted = _utc(submitted_at_utc, "submitted_at_utc")
    expires = _utc(expires_at_utc, "expires_at_utc")
    if not signal < submitted < expires:
        raise ValueError("maker timing must satisfy signal < submission < expiry")
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    limit_text = _decimal_text(limit_price, "limit_price", positive=True)
    requested_text = _decimal_text(
        requested_base_quantity,
        "requested_base_quantity",
        positive=True,
    )
    queue_text = _decimal_text(queue_ahead_base_quantity, "queue_ahead_base_quantity")
    limit = Decimal(limit_text)
    requested = Decimal(requested_text)
    queue_initial = Decimal(queue_text)
    queue_remaining = queue_initial
    filled = Decimal("0")
    touch_quantity = Decimal("0")
    trade_through_quantity = Decimal("0")
    queue_consumed = Decimal("0")
    touch_count = 0
    through_count = 0
    first_trade_through_at: datetime | None = None
    filled_at: datetime | None = None

    for trade in snapshot.trades:
        if not submitted < trade.observed_at_utc < expires:
            continue
        price = Decimal(trade.price)
        quantity = Decimal(trade.base_quantity)
        is_opposite_taker = (side == "buy" and trade.taker_side == "sell") or (
            side == "sell" and trade.taker_side == "buy"
        )
        if not is_opposite_taker:
            continue
        if price == limit:
            touch_count += 1
            touch_quantity += quantity
            continue
        is_trade_through = (side == "buy" and price < limit) or (side == "sell" and price > limit)
        if not is_trade_through:
            continue
        through_count += 1
        trade_through_quantity += quantity
        if first_trade_through_at is None:
            first_trade_through_at = trade.observed_at_utc
        consumed = min(queue_remaining, quantity)
        queue_remaining -= consumed
        queue_consumed += consumed
        available = quantity - consumed
        if available <= 0:
            continue
        order_fill = min(requested - filled, available)
        filled += order_fill
        if filled == requested:
            filled_at = trade.observed_at_utc
            break

    unfilled = requested - filled
    if filled == requested:
        outcome: Literal["filled", "cancelled_partial", "cancelled_no_fill"] = "filled"
        cancelled_at = None
        requote_eligible = False
    elif filled > 0:
        outcome = "cancelled_partial"
        cancelled_at = expires
        requote_eligible = True
    else:
        outcome = "cancelled_no_fill"
        cancelled_at = expires
        requote_eligible = True
    average_fill_price = limit if filled > 0 else Decimal("0")
    exchange_fee_quote = filled * average_fill_price * _EXCHANGE_FEE_ONE_WAY_BPS / Decimal("10000")
    return MakerFillReplay(
        order_intent_id=order_intent_id,
        trade_snapshot_id=snapshot.snapshot_id,
        trade_source_sha256=snapshot.source_sha256,
        instrument_id=snapshot.instrument_id,
        side=side,
        signal_at_utc=signal,
        submitted_at_utc=submitted,
        expires_at_utc=expires,
        limit_price=limit_text,
        requested_base_quantity=requested_text,
        queue_ahead_base_quantity=queue_text,
        outcome=outcome,
        filled_base_quantity=_format_decimal(filled),
        unfilled_base_quantity=_format_decimal(unfilled),
        average_fill_price=_format_decimal(average_fill_price),
        exchange_fee_one_way_bps=_format_decimal(_EXCHANGE_FEE_ONE_WAY_BPS),
        exchange_fee_quote=_format_decimal(exchange_fee_quote),
        touch_trade_count=touch_count,
        touch_base_quantity=_format_decimal(touch_quantity),
        trade_through_trade_count=through_count,
        trade_through_base_quantity=_format_decimal(trade_through_quantity),
        queue_consumed_base_quantity=_format_decimal(queue_consumed),
        remaining_queue_ahead_base_quantity=_format_decimal(queue_remaining),
        first_trade_through_at_utc=first_trade_through_at,
        filled_at_utc=filled_at,
        cancelled_at_utc=cancelled_at,
        requote_eligible=requote_eligible,
    )
