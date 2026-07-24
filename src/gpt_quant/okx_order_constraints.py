from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .okx_instruments import OKXSpotInstrumentSnapshot

_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")


def _utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(UTC)


def _maximum_age(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("maximum_snapshot_age_ms must be a non-negative integer")
    return value


def _positive_canonical_decimal(value: str, *, field: str) -> tuple[str, Decimal]:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise ValueError(f"{field} must be a canonical positive decimal")
    parsed = Decimal(value)
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError(f"{field} must be a canonical positive decimal")
    canonical = format(parsed, "f")
    if "." in canonical:
        canonical = canonical.rstrip("0").rstrip(".")
    if canonical != value:
        raise ValueError(f"{field} must use canonical decimal encoding")
    return value, parsed


def _exchange_time_upper_bound(
    snapshot: OKXSpotInstrumentSnapshot,
    *,
    local_time_utc: datetime,
) -> datetime:
    """Project one local timestamp into the conservative OKX clock bound."""

    return local_time_utc + timedelta(
        seconds=snapshot.midpoint_clock_skew_seconds + snapshot.server_round_trip_seconds / 2
    )


def validate_okx_spot_order_quantity(
    snapshot: OKXSpotInstrumentSnapshot,
    *,
    submitted_at_utc: datetime,
    maximum_snapshot_age_ms: int,
    base_quantity: str,
) -> str:
    """Validate one proposed OKX spot base quantity before any execution adapter.

    This function performs no network or account operation. It requires an exact,
    replay-validated public instrument snapshot and rejects unavailable, stale,
    expired, below-minimum, or off-lot quantities. Snapshot age is measured only
    in the local clock domain. Exchange-effective constraint changes are compared
    against a conservative exchange-time upper bound derived from the validated
    public-time request envelope. Minimum quote notional still requires a separate
    current executable quote and is intentionally not inferred here.
    """

    if not isinstance(snapshot, OKXSpotInstrumentSnapshot):
        raise TypeError("snapshot must be an OKXSpotInstrumentSnapshot")
    submitted_at = _utc(submitted_at_utc, field="submitted_at_utc")
    maximum_age_ms = _maximum_age(maximum_snapshot_age_ms)
    instrument_received = _utc(
        snapshot.response_received_utc,
        field="snapshot.response_received_utc",
    )
    evidence_available = _utc(
        snapshot.server_time_response_received_utc,
        field="snapshot.server_time_response_received_utc",
    )
    if submitted_at < evidence_available:
        raise ValueError("order submission cannot predate complete instrument timing evidence")
    if submitted_at - instrument_received > timedelta(milliseconds=maximum_age_ms):
        raise ValueError("OKX instrument snapshot is stale at order submission")
    if snapshot.valid_until_utc is not None:
        exchange_time_upper_bound = _exchange_time_upper_bound(
            snapshot,
            local_time_utc=submitted_at,
        )
        if exchange_time_upper_bound >= snapshot.valid_until_utc:
            raise ValueError("OKX instrument snapshot is no longer valid at order submission")

    canonical_quantity, quantity = _positive_canonical_decimal(
        base_quantity,
        field="base_quantity",
    )
    minimum = snapshot.minimum_order_size_base_decimal
    lot_size = snapshot.lot_size_decimal
    if quantity < minimum:
        raise ValueError("base_quantity is below the OKX minimum order size")
    if quantity % lot_size != 0:
        raise ValueError("base_quantity is not an exact multiple of the OKX lot size")
    return canonical_quantity


def validate_okx_spot_limit_order_constraints(
    snapshot: OKXSpotInstrumentSnapshot,
    *,
    submitted_at_utc: datetime,
    maximum_snapshot_age_ms: int,
    base_quantity: str,
    limit_price: str,
) -> tuple[str, str]:
    """Validate quantity and tick alignment for one offline OKX spot limit intent.

    This is a pre-adapter constraint gate, not an order submission. It deliberately
    does not infer minimum quote notional, spread, slippage, impact, latency or fill
    probability; those require separately versioned current quote and cost evidence.
    """

    canonical_quantity = validate_okx_spot_order_quantity(
        snapshot,
        submitted_at_utc=submitted_at_utc,
        maximum_snapshot_age_ms=maximum_snapshot_age_ms,
        base_quantity=base_quantity,
    )
    canonical_price, price = _positive_canonical_decimal(limit_price, field="limit_price")
    if price % snapshot.tick_size_decimal != 0:
        raise ValueError("limit_price is not an exact multiple of the OKX tick size")
    return canonical_quantity, canonical_price
