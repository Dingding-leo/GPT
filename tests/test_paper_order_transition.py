from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gpt_quant.paper_order_transition import (
    PaperOrderStateTransitionRequest,
    advance_paper_order_transition,
    build_initial_paper_order_transition,
)
from gpt_quant.paper_post_only_order_intent import PaperPostOnlyOrderIntent
from gpt_quant.paper_submission_identity import PaperSubmissionIdentity

# Exact public OKX BTC-USDT response hashes pinned by the maker-intent parent suite.
_REAL_OKX_QUOTE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_INSTRUMENT_SHA256 = "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"


def _at(microsecond: int) -> datetime:
    return datetime(2026, 7, 21, 0, 0, 0, microsecond, tzinfo=UTC)


def _intent(*, created_microsecond: int = 450_000) -> PaperPostOnlyOrderIntent:
    return PaperPostOnlyOrderIntent(
        decision_id="3" * 64,
        target_intent_id="5" * 64,
        quote_snapshot_id=_REAL_OKX_QUOTE_SHA256,
        instrument_snapshot_sha256=_REAL_OKX_INSTRUMENT_SHA256,
        instrument_id="BTC-USDT",
        decision_at_utc=_at(400_000),
        created_at_utc=_at(created_microsecond),
        expires_at_utc=_at(900_000),
        quote_observed_at_utc=_at(200_000),
        quote_received_at_utc=_at(350_000),
        maximum_quote_age_ms=500,
        side="buy",
        base_quantity="0.001",
        limit_price="66113.8",
        reference_bid_price="66113.8",
        reference_ask_price="66114",
    )


def _acknowledged() -> tuple[
    PaperPostOnlyOrderIntent,
    PaperSubmissionIdentity,
    PaperOrderStateTransitionRequest,
]:
    intent = _intent()
    identity = PaperSubmissionIdentity.from_order_intent(intent)
    acknowledgement = build_initial_paper_order_transition(
        identity,
        intent,
        event_type="acknowledged",
        occurred_at_utc=_at(500_000),
    )
    return intent, identity, acknowledgement


def test_initial_acknowledgement_is_canonical_and_reconstructable() -> None:
    intent, identity, acknowledgement = _acknowledged()
    replay = PaperOrderStateTransitionRequest.from_json_bytes(acknowledgement.to_json_bytes())

    assert replay == acknowledgement
    assert acknowledgement.sequence == 0
    assert acknowledgement.previous_event_id is None
    assert acknowledgement.remaining_base_quantity == intent.base_quantity
    assert acknowledgement.exchange_fee_bps == "5"
    assert acknowledgement.exchange_fee_quote_delta == "0"
    acknowledgement.assert_matches_evidence(identity, intent)
    acknowledgement.assert_reconstructs(identity, intent)
    acknowledgement.assert_idempotent_retry(replay)


def test_no_fill_cannot_smuggle_a_fill_or_fee() -> None:
    intent, identity, acknowledgement = _acknowledged()
    no_fill = advance_paper_order_transition(
        acknowledgement,
        identity,
        intent,
        event_type="no_fill",
        occurred_at_utc=_at(550_000),
    )

    assert no_fill.remaining_base_quantity == "0.001"
    assert no_fill.filled_base_quantity_delta == "0"
    assert no_fill.fill_price is None
    assert no_fill.exchange_fee_quote_delta == "0"
    with pytest.raises(ValueError, match="does not permit a fill quantity"):
        advance_paper_order_transition(
            acknowledgement,
            identity,
            intent,
            event_type="no_fill",
            occurred_at_utc=_at(550_000),
            filled_base_quantity_delta="0.0001",
            fill_price="66113.8",
        )


def test_partial_and_final_fills_charge_exactly_five_bps_on_each_fill_delta() -> None:
    intent, identity, acknowledgement = _acknowledged()
    partial = advance_paper_order_transition(
        acknowledgement,
        identity,
        intent,
        event_type="partial_fill",
        occurred_at_utc=_at(600_000),
        filled_base_quantity_delta="0.0004",
        fill_price="66113.8",
    )
    filled = advance_paper_order_transition(
        partial,
        identity,
        intent,
        event_type="filled",
        occurred_at_utc=_at(700_000),
        filled_base_quantity_delta="0.0006",
        fill_price="66113.8",
    )

    assert partial.remaining_base_quantity == "0.0006"
    assert partial.exchange_fee_quote_delta == "0.01322276"
    assert filled.remaining_base_quantity == "0"
    assert filled.exchange_fee_quote_delta == "0.01983414"
    partial.assert_reconstructs(identity, intent, previous=acknowledgement)
    filled.assert_reconstructs(identity, intent, previous=partial)
    with pytest.raises(ValueError, match="exact remaining quantity"):
        advance_paper_order_transition(
            partial,
            identity,
            intent,
            event_type="filled",
            occurred_at_utc=_at(700_000),
            filled_base_quantity_delta="0.0005",
            fill_price="66113.8",
        )


def test_timeout_and_cancellation_respect_exclusive_expiry_boundary() -> None:
    intent, identity, acknowledgement = _acknowledged()

    with pytest.raises(ValueError, match="cannot occur before"):
        advance_paper_order_transition(
            acknowledgement,
            identity,
            intent,
            event_type="timed_out",
            occurred_at_utc=_at(899_999),
        )
    timed_out = advance_paper_order_transition(
        acknowledgement,
        identity,
        intent,
        event_type="timed_out",
        occurred_at_utc=_at(900_000),
    )
    cancelled = advance_paper_order_transition(
        acknowledgement,
        identity,
        intent,
        event_type="cancelled",
        occurred_at_utc=_at(899_999),
    )

    assert timed_out.remaining_base_quantity == "0.001"
    assert cancelled.remaining_base_quantity == "0.001"
    with pytest.raises(ValueError, match="before the exclusive intent expiry"):
        advance_paper_order_transition(
            acknowledgement,
            identity,
            intent,
            event_type="cancelled",
            occurred_at_utc=_at(900_000),
        )


def test_requote_requires_explicit_terminal_unfilled_transition() -> None:
    intent, identity, acknowledgement = _acknowledged()
    timed_out = advance_paper_order_transition(
        acknowledgement,
        identity,
        intent,
        event_type="timed_out",
        occurred_at_utc=_at(900_000),
    )
    requote = advance_paper_order_transition(
        timed_out,
        identity,
        intent,
        event_type="requote_requested",
        occurred_at_utc=_at(900_001),
    )

    assert requote.previous_event_id == timed_out.event_id
    assert requote.remaining_base_quantity == "0.001"
    with pytest.raises(ValueError, match="cannot transition"):
        advance_paper_order_transition(
            acknowledgement,
            identity,
            intent,
            event_type="requote_requested",
            occurred_at_utc=_at(550_000),
        )


def test_duplicate_delivery_is_idempotent_but_conflicting_same_sequence_fails() -> None:
    intent, identity, acknowledgement = _acknowledged()
    exact_retry = build_initial_paper_order_transition(
        identity,
        intent,
        event_type="acknowledged",
        occurred_at_utc=_at(500_000),
    )
    conflicting = build_initial_paper_order_transition(
        identity,
        intent,
        event_type="rejected",
        occurred_at_utc=_at(500_000),
    )

    acknowledgement.assert_idempotent_retry(exact_retry)
    with pytest.raises(ValueError, match="conflicts with the existing lifecycle action"):
        acknowledgement.assert_idempotent_retry(conflicting)


def test_transition_rejects_changed_intent_and_duplicate_serialized_fields() -> None:
    intent, identity, acknowledgement = _acknowledged()
    changed_intent = _intent(created_microsecond=451_000)

    with pytest.raises(ValueError, match="does not reconstruct from the exact order intent"):
        acknowledgement.assert_matches_evidence(identity, changed_intent)

    serialized = acknowledgement.to_json_bytes()
    duplicate = serialized.replace(
        b'{"decision_id":',
        b'{"decision_id":"' + (b"3" * 64) + b'","decision_id":',
        1,
    )
    with pytest.raises(ValueError, match="duplicate field"):
        PaperOrderStateTransitionRequest.from_json_bytes(duplicate)
