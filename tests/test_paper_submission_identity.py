from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from gpt_quant.paper_post_only_order_intent import PaperPostOnlyOrderIntent
from gpt_quant.paper_submission_identity import PaperSubmissionIdentity

# Exact public OKX BTC-USDT response hashes pinned by the maker-intent parent suite.
_REAL_OKX_QUOTE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_INSTRUMENT_SHA256 = "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"
_DECISION_ID = "3" * 64
_OTHER_DECISION_ID = "4" * 64


def _intent(
    *,
    decision_id: str = _DECISION_ID,
    created_microsecond: int = 450_000,
) -> PaperPostOnlyOrderIntent:
    return PaperPostOnlyOrderIntent(
        decision_id=decision_id,
        target_intent_id="5" * 64,
        quote_snapshot_id=_REAL_OKX_QUOTE_SHA256,
        instrument_snapshot_sha256=_REAL_OKX_INSTRUMENT_SHA256,
        instrument_id="BTC-USDT",
        decision_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        created_at_utc=datetime(
            2026,
            7,
            21,
            0,
            0,
            0,
            created_microsecond,
            tzinfo=UTC,
        ),
        expires_at_utc=datetime(2026, 7, 21, 0, 0, 0, 900_000, tzinfo=UTC),
        quote_observed_at_utc=datetime(2026, 7, 21, 0, 0, 0, 200_000, tzinfo=UTC),
        quote_received_at_utc=datetime(2026, 7, 21, 0, 0, 0, 350_000, tzinfo=UTC),
        maximum_quote_age_ms=500,
        side="buy",
        base_quantity="0.001",
        limit_price="66113.8",
        reference_bid_price="66113.8",
        reference_ask_price="66114",
    )


def test_exact_retry_reuses_one_submission_key_and_exact_intent() -> None:
    intent = _intent()
    first = PaperSubmissionIdentity.from_order_intent(intent)
    retry = PaperSubmissionIdentity.from_order_intent(
        PaperPostOnlyOrderIntent.from_json_bytes(intent.to_json_bytes())
    )

    assert first == retry
    assert first.record_id == intent.order_intent_id
    assert first.record_sha256 == hashlib.sha256(intent.to_json_bytes()).hexdigest()
    assert first.submission_key != first.record_id
    first.assert_reconstructs(intent)
    first.assert_idempotent_retry(retry)


def test_changed_intent_cannot_become_a_second_initial_order() -> None:
    first = PaperSubmissionIdentity.from_order_intent(_intent())
    later = PaperSubmissionIdentity.from_order_intent(_intent(created_microsecond=451_000))

    assert later.submission_key == first.submission_key
    assert later.record_id != first.record_id
    assert later.record_sha256 != first.record_sha256
    with pytest.raises(ValueError, match="conflicts with the initial request"):
        first.assert_idempotent_retry(later)


def test_distinct_paper_decisions_receive_distinct_submission_keys() -> None:
    first = PaperSubmissionIdentity.from_order_intent(_intent())
    second = PaperSubmissionIdentity.from_order_intent(_intent(decision_id=_OTHER_DECISION_ID))

    assert first.submission_key != second.submission_key
    with pytest.raises(ValueError, match="different paper decision"):
        first.assert_idempotent_retry(second)


def test_identity_rejects_arbitrary_record_bytes_and_ids() -> None:
    invalid = b"arbitrary canonical-looking bytes"
    with pytest.raises(TypeError, match="PaperPostOnlyOrderIntent"):
        PaperSubmissionIdentity.from_order_intent(invalid)  # type: ignore[arg-type]


def test_identity_rejects_reconstruction_from_changed_intent() -> None:
    identity = PaperSubmissionIdentity.from_order_intent(_intent())

    with pytest.raises(ValueError, match="does not reconstruct from the exact order intent"):
        identity.assert_reconstructs(_intent(created_microsecond=451_000))
