from __future__ import annotations

import re
from decimal import Decimal, localcontext

from .execution_quote import ExecutionQuoteSnapshot
from .okx_instruments import OKXSpotInstrumentSnapshot
from .okx_order_constraints import validate_okx_spot_limit_order_constraints
from .paper_post_only_order_intent import PaperPostOnlyOrderIntent

__all__ = ["validate_okx_paper_post_only_order_intent_constraints"]

_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?")


def _positive_canonical_decimal(value: str, *, field: str) -> Decimal:
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
    return parsed


def validate_okx_paper_post_only_order_intent_constraints(
    snapshot: OKXSpotInstrumentSnapshot,
    quote: ExecutionQuoteSnapshot,
    intent: PaperPostOnlyOrderIntent,
    *,
    maximum_snapshot_age_ms: int,
    minimum_paper_quote_notional: str,
) -> None:
    """Bind one maker paper intent to exact public OKX order constraints.

    This offline gate performs no account or order operation. It verifies that the
    intent reproduces the supplied quote and immutable instrument response, then
    enforces the exact OKX lot and tick increments plus one explicit paper-policy
    quote-notional floor at the maker limit. The floor is not an inferred exchange
    minimum, and no spread, slippage, impact, latency, or fill probability is added.
    """

    if not isinstance(snapshot, OKXSpotInstrumentSnapshot):
        raise TypeError("snapshot must be an OKXSpotInstrumentSnapshot")
    if not isinstance(quote, ExecutionQuoteSnapshot):
        raise TypeError("quote must be an ExecutionQuoteSnapshot")
    if not isinstance(intent, PaperPostOnlyOrderIntent):
        raise TypeError("intent must be a PaperPostOnlyOrderIntent")

    if quote.instrument_snapshot_sha256 != snapshot.raw_response_sha256:
        raise ValueError("execution quote does not reference the supplied OKX instrument snapshot")
    if intent.instrument_snapshot_sha256 != snapshot.raw_response_sha256:
        raise ValueError(
            "post-only order intent does not reference the supplied OKX instrument snapshot"
        )
    if (
        snapshot.instrument_id != quote.instrument_id
        or quote.instrument_id != intent.instrument_id
    ):
        raise ValueError(
            "post-only order intent instrument does not match the supplied OKX evidence"
        )
    if intent.quote_snapshot_id != quote.snapshot_id:
        raise ValueError("post-only order intent does not reference the supplied execution quote")
    if (
        intent.quote_observed_at_utc != quote.observed_at_utc
        or intent.quote_received_at_utc != quote.received_at_utc
        or intent.reference_bid_price != quote.bid_price
        or intent.reference_ask_price != quote.ask_price
    ):
        raise ValueError("post-only order intent does not reproduce the supplied execution quote")

    validate_okx_spot_limit_order_constraints(
        snapshot,
        submitted_at_utc=intent.created_at_utc,
        maximum_snapshot_age_ms=maximum_snapshot_age_ms,
        base_quantity=intent.base_quantity,
        limit_price=intent.limit_price,
    )

    minimum_notional = _positive_canonical_decimal(
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
        raise ValueError("post-only order quote notional is below the declared paper minimum")
