from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pytest

from gpt_quant.paper_order_transition import (
    PaperOrderStateTransitionRequest,
    advance_paper_order_transition,
    build_initial_paper_order_transition,
)
from gpt_quant.paper_post_only_order_intent import PaperPostOnlyOrderIntent
from gpt_quant.paper_submission_identity import PaperSubmissionIdentity

_REAL_OKX_QUOTE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_INSTRUMENT_SHA256 = "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"


def _at(microsecond: int) -> datetime:
    return datetime(2026, 7, 21, 0, 0, 0, microsecond, tzinfo=UTC)


def _intent(side: Literal["buy", "sell"]) -> PaperPostOnlyOrderIntent:
    return PaperPostOnlyOrderIntent(
        decision_id="3" * 64,
        target_intent_id="5" * 64,
        quote_snapshot_id=_REAL_OKX_QUOTE_SHA256,
        instrument_snapshot_sha256=_REAL_OKX_INSTRUMENT_SHA256,
        instrument_id="BTC-USDT",
        decision_at_utc=_at(400_000),
        created_at_utc=_at(450_000),
        expires_at_utc=_at(900_000),
        quote_observed_at_utc=_at(200_000),
        quote_received_at_utc=_at(350_000),
        maximum_quote_age_ms=500,
        side=side,
        base_quantity="0.001",
        limit_price="66113.8" if side == "buy" else "66114",
        reference_bid_price="66113.8",
        reference_ask_price="66114",
    )


def _acknowledged(
    side: Literal["buy", "sell"],
) -> tuple[
    PaperPostOnlyOrderIntent,
    PaperSubmissionIdentity,
    PaperOrderStateTransitionRequest,
]:
    intent = _intent(side)
    identity = PaperSubmissionIdentity.from_order_intent(intent)
    acknowledgement = build_initial_paper_order_transition(
        identity,
        intent,
        event_type="acknowledged",
        occurred_at_utc=_at(500_000),
    )
    return intent, identity, acknowledgement


@pytest.mark.parametrize(
    ("side", "fill_price"),
    [
        ("buy", "66113.8"),
        ("buy", "66113.7"),
        ("sell", "66114"),
        ("sell", "66114.1"),
    ],
)
def test_maker_fill_accepts_exact_limit_and_price_improvement(
    side: Literal["buy", "sell"],
    fill_price: str,
) -> None:
    intent, identity, acknowledgement = _acknowledged(side)

    fill = advance_paper_order_transition(
        acknowledgement,
        identity,
        intent,
        event_type="partial_fill",
        occurred_at_utc=_at(600_000),
        filled_base_quantity_delta="0.0004",
        fill_price=fill_price,
    )

    assert fill.fill_price == fill_price
    fill.assert_matches_evidence(identity, intent)
    fill.assert_reconstructs(identity, intent, previous=acknowledgement)


@pytest.mark.parametrize(
    ("side", "fill_price", "message"),
    [
        ("buy", "66113.9", "buy fill cannot exceed"),
        ("sell", "66113.9", "sell fill cannot be below"),
    ],
)
def test_maker_fill_rejects_one_tick_price_violation(
    side: Literal["buy", "sell"],
    fill_price: str,
    message: str,
) -> None:
    intent, identity, acknowledgement = _acknowledged(side)

    with pytest.raises(ValueError, match=message):
        advance_paper_order_transition(
            acknowledgement,
            identity,
            intent,
            event_type="partial_fill",
            occurred_at_utc=_at(600_000),
            filled_base_quantity_delta="0.0004",
            fill_price=fill_price,
        )


def test_self_rehashed_worse_buy_fill_fails_exact_intent_evidence() -> None:
    intent, identity, acknowledgement = _acknowledged("buy")
    forged = PaperOrderStateTransitionRequest(
        decision_id=identity.decision_id,
        submission_key=identity.submission_key,
        order_intent_id=identity.record_id,
        order_intent_sha256=identity.record_sha256,
        event_type="partial_fill",
        sequence=1,
        previous_event_id=acknowledgement.event_id,
        occurred_at_utc=_at(600_000),
        requested_base_quantity="0.001",
        filled_base_quantity_delta="0.0004",
        fill_price="66113.9",
        exchange_fee_quote_delta="0.01322278",
        remaining_base_quantity="0.0006",
    )

    with pytest.raises(ValueError, match="buy fill cannot exceed"):
        forged.assert_matches_evidence(identity, intent)
