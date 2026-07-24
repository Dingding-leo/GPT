from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext

from .execution_quote import ExecutionQuoteSnapshot
from .okx_instruments import OKXSpotInstrumentSnapshot
from .paper_execution_attempt import PaperExecutionAttempt
from .paper_post_only_order_intent import PaperPostOnlyOrderIntent

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


def validate_okx_paper_post_only_order_intent_constraints(
    snapshot: OKXSpotInstrumentSnapshot,
    quote: ExecutionQuoteSnapshot,
    intent: PaperPostOnlyOrderIntent,
    *,
    maximum_snapshot_age_ms: int,
    minimum_paper_quote_notional: str,
) -> None:
    """Bind one maker paper intent to exact OKX instrument and quote constraints.

    The generic post-only intent proves deterministic lineage and maker-side pricing,
    but it is provider-neutral. This offline pre-adapter gate additionally proves that
    the persisted OKX instrument response matches the quote and intent, the intended
    quantity and limit align to current lot/tick constraints, and the order meets one
    explicit paper-policy quote-notional floor. It performs no network or account
    operation and makes no acknowledgement or fill claim.
    """

    if not isinstance(snapshot, OKXSpotInstrumentSnapshot):
        raise TypeError("snapshot must be an OKXSpotInstrumentSnapshot")
    if not isinstance(quote, ExecutionQuoteSnapshot):
        raise TypeError("quote must be an ExecutionQuoteSnapshot")
    if not isinstance(intent, PaperPostOnlyOrderIntent):
        raise TypeError("intent must be a PaperPostOnlyOrderIntent")

    if (
        quote.instrument_snapshot_sha256 != snapshot.raw_response_sha256
        or intent.instrument_snapshot_sha256 != snapshot.raw_response_sha256
    ):
        raise ValueError(
            "maker order intent does not reference the supplied OKX instrument snapshot"
        )
    if (
        quote.instrument_id != snapshot.instrument_id
        or intent.instrument_id != quote.instrument_id
    ):
        raise ValueError("maker order instrument does not match the supplied OKX evidence")
    if intent.quote_snapshot_id != quote.snapshot_id:
        raise ValueError("maker order intent does not reference the supplied execution quote")
    if (
        intent.quote_observed_at_utc != quote.observed_at_utc
        or intent.quote_received_at_utc != quote.received_at_utc
        or intent.reference_bid_price != quote.bid_price
        or intent.reference_ask_price != quote.ask_price
    ):
        raise ValueError("maker order intent does not reproduce the supplied execution quote")

    validate_okx_spot_limit_order_constraints(
        snapshot,
        submitted_at_utc=intent.created_at_utc,
        maximum_snapshot_age_ms=maximum_snapshot_age_ms,
        base_quantity=intent.base_quantity,
        limit_price=intent.limit_price,
    )

    _, minimum_notional = _positive_canonical_decimal(
        minimum_paper_quote_notional,
        field="minimum_paper_quote_notional",
    )
    quantity = Decimal(intent.base_quantity)
    limit_price = Decimal(intent.limit_price)
    with localcontext() as context:
        context.prec = max(
            len(quantity.as_tuple().digits) + len(limit_price.as_tuple().digits),
            len(minimum_notional.as_tuple().digits),
            28,
        )
        requested_quote_notional = quantity * limit_price
    if requested_quote_notional < minimum_notional:
        raise ValueError("maker order quote notional is below the declared paper minimum")


def validate_okx_paper_execution_attempt_constraints(
    snapshot: OKXSpotInstrumentSnapshot,
    quote: ExecutionQuoteSnapshot,
    attempt: PaperExecutionAttempt,
    *,
    maximum_snapshot_age_ms: int,
    minimum_paper_quote_notional: str,
) -> None:
    """Bind one paper attempt to exact OKX instrument and touch-capacity evidence.

    This offline gate performs no network or account operation. It proves that the
    attempt references the supplied quote and immutable instrument response, that the
    requested quantity was valid when submitted, meets one explicit paper-policy quote
    notional floor at the conservative touch, and that any claimed fill is aligned to the
    exchange lot and tick size and no larger than visible same-side top-of-book quantity.
    The floor is a caller-declared paper constraint, not an inferred OKX exchange minimum.
    This gate does not infer deeper liquidity, slippage or impact.
    """

    if not isinstance(snapshot, OKXSpotInstrumentSnapshot):
        raise TypeError("snapshot must be an OKXSpotInstrumentSnapshot")
    if not isinstance(quote, ExecutionQuoteSnapshot):
        raise TypeError("quote must be an ExecutionQuoteSnapshot")
    if not isinstance(attempt, PaperExecutionAttempt):
        raise TypeError("attempt must be a PaperExecutionAttempt")

    if quote.instrument_snapshot_sha256 != snapshot.raw_response_sha256:
        raise ValueError("execution quote does not reference the supplied OKX instrument snapshot")
    if (
        quote.instrument_id != snapshot.instrument_id
        or attempt.instrument_id != quote.instrument_id
    ):
        raise ValueError("paper execution instrument does not match the supplied OKX evidence")
    if attempt.quote_snapshot_id != quote.snapshot_id:
        raise ValueError("paper execution attempt does not reference the supplied quote")
    if (
        attempt.quote_observed_at_utc != quote.observed_at_utc
        or attempt.quote_received_at_utc != quote.received_at_utc
        or attempt.reference_bid_price != quote.bid_price
        or attempt.reference_ask_price != quote.ask_price
    ):
        raise ValueError("paper execution attempt does not reproduce the supplied quote")

    validate_okx_spot_order_quantity(
        snapshot,
        submitted_at_utc=attempt.submitted_at_utc,
        maximum_snapshot_age_ms=maximum_snapshot_age_ms,
        base_quantity=attempt.requested_base_quantity,
    )

    _, minimum_notional = _positive_canonical_decimal(
        minimum_paper_quote_notional,
        field="minimum_paper_quote_notional",
    )
    requested = Decimal(attempt.requested_base_quantity)
    reference_touch_price = Decimal(quote.ask_price if attempt.side == "buy" else quote.bid_price)
    with localcontext() as context:
        context.prec = max(
            len(requested.as_tuple().digits) + len(reference_touch_price.as_tuple().digits),
            len(minimum_notional.as_tuple().digits),
            28,
        )
        requested_quote_notional = requested * reference_touch_price
    if requested_quote_notional < minimum_notional:
        raise ValueError("requested quote notional is below the declared paper minimum")

    filled = Decimal(attempt.filled_base_quantity)
    if filled % snapshot.lot_size_decimal != 0:
        raise ValueError("filled_base_quantity is not an exact multiple of the OKX lot size")
    if filled == 0:
        return

    average_fill_price = Decimal(attempt.average_fill_price)
    if average_fill_price % snapshot.tick_size_decimal != 0:
        raise ValueError("average_fill_price is not an exact multiple of the OKX tick size")

    visible_touch_quantity = Decimal(
        quote.ask_quantity if attempt.side == "buy" else quote.bid_quantity
    )
    if filled > visible_touch_quantity:
        raise ValueError("filled_base_quantity exceeds the supplied same-side top-of-book quantity")
