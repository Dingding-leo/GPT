from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.paper_order_decision import PaperOrderDecision
from gpt_quant.paper_post_only_order_intent import (
    PaperPostOnlyOrderIntent,
    build_paper_post_only_order_intent,
)

# Official public OKX BTC-USDT depth-one response and instrument evidence already
# pinned by the execution-quote regression suite.
_REAL_OKX_RESPONSE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_INSTRUMENT_SHA256 = "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"
_SPREAD_BPS = "0.030250824713108741127054976336292368170687253361245"


def _quote() -> ExecutionQuoteSnapshot:
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime(2026, 7, 21, 0, 0, 0, 300_000, tzinfo=UTC),
        received_at_utc=datetime(2026, 7, 21, 0, 0, 0, 350_000, tzinfo=UTC),
        bid_price="66113.8",
        bid_quantity="0.42",
        ask_price="66114",
        ask_quantity="0.37",
        source_response_sha256=_REAL_OKX_RESPONSE_SHA256,
        instrument_snapshot_sha256=_REAL_OKX_INSTRUMENT_SHA256,
    )


def _decision(
    *,
    side: str = "buy",
    order_type: str = "post_only_limit",
    exchange_fee_bps: str = "5",
    market_snapshot_sha256: str | None = None,
) -> PaperOrderDecision:
    quote = _quote()
    return PaperOrderDecision(
        target_intent_id="1" * 64,
        instrument_id="BTC-USDT",
        decided_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        market_observed_at_utc=quote.observed_at_utc,
        outcome="planned",
        reason_code="pretrade_passed",
        order_type=order_type,
        side=side,
        base_quantity="0.001",
        instrument_snapshot_sha256=quote.instrument_snapshot_sha256,
        market_snapshot_sha256=market_snapshot_sha256 or quote.snapshot_id,
        portfolio_state_before_sha256="4" * 64,
        risk_state_before_sha256="5" * 64,
        exchange_fee_bps=exchange_fee_bps,
        spread_bps=_SPREAD_BPS,
        slippage_bps="0",
        market_impact_bps="0",
        latency_ms=50,
    )


def _intent(
    *,
    decision: PaperOrderDecision | None = None,
    created_at_utc: datetime | str = datetime(2026, 7, 21, 0, 0, 0, 450_000, tzinfo=UTC),
    maximum_quote_age_ms: int = 250,
    limit_price: str = "66113.8",
) -> PaperPostOnlyOrderIntent:
    return build_paper_post_only_order_intent(
        decision or _decision(),
        _quote(),
        created_at_utc=created_at_utc,
        expires_at_utc=datetime(2026, 7, 21, 0, 0, 2, tzinfo=UTC),
        maximum_quote_age_ms=maximum_quote_age_ms,
        limit_price=limit_price,
    )


def test_post_only_order_intent_is_canonical_idempotent_and_reconstructable() -> None:
    decision = _decision()
    quote = _quote()
    intent = _intent(decision=decision)
    replayed = PaperPostOnlyOrderIntent.from_json_bytes(intent.to_json_bytes())

    assert replayed == intent
    assert replayed.time_in_force == "post_only"
    assert replayed.exchange_fee_bps == "5"
    assert replayed.limit_price == quote.bid_price
    assert replayed.quote_snapshot_id == quote.snapshot_id
    replayed.assert_reconstructs(decision, quote)

    payload = json.loads(replayed.to_json_bytes())
    assert "spread_bps" not in payload
    assert "slippage_bps" not in payload
    assert "market_impact_bps" not in payload
    assert "latency_ms" not in payload


def test_timezone_equivalent_inputs_preserve_order_intent_identity() -> None:
    utc_intent = _intent()
    adelaide = timezone(timedelta(hours=9, minutes=30))
    offset_intent = _intent(
        created_at_utc=datetime(2026, 7, 21, 9, 30, 0, 450_000, tzinfo=adelaide)
    )

    assert offset_intent.order_intent_id == utc_intent.order_intent_id
    assert offset_intent.to_json_bytes() == utc_intent.to_json_bytes()


def test_post_only_order_intent_rejects_taker_or_stale_requests() -> None:
    with pytest.raises(ValueError, match="at or below the reference bid"):
        _intent(limit_price="66113.9")

    with pytest.raises(ValueError, match="stale"):
        _intent(
            created_at_utc=datetime(2026, 7, 21, 0, 0, 0, 600_000, tzinfo=UTC),
            maximum_quote_age_ms=250,
        )


def test_post_only_order_intent_requires_exact_decision_quote_and_five_bps_fee() -> None:
    with pytest.raises(ValueError, match="planned post-only limit decision"):
        _intent(decision=_decision(order_type="market"))

    with pytest.raises(ValueError, match="exactly 5 bps"):
        _intent(decision=_decision(exchange_fee_bps="6"))

    with pytest.raises(ValueError, match="exact execution quote"):
        _intent(decision=_decision(market_snapshot_sha256="9" * 64))


def test_post_only_sell_requires_limit_at_or_above_reference_ask() -> None:
    decision = _decision(side="sell")
    accepted = _intent(decision=decision, limit_price="66114")
    assert accepted.side == "sell"

    with pytest.raises(ValueError, match="at or above the reference ask"):
        _intent(decision=decision, limit_price="66113.9")
