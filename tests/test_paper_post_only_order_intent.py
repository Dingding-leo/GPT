from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
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
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _target(
    *,
    config_sha256: str = _CONFIG_SHA256,
    decision_not_before_utc: datetime | None = None,
) -> TargetPositionIntent:
    if decision_not_before_utc is None:
        decision_not_before_utc = datetime(2026, 7, 21, 0, 0, 0, 200_000, tzinfo=UTC)
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1H",
        strategy_id="canonical-one-hour-five-bps",
        strategy_revision="e5e7ef22a23e6673c0183f47c0398f6af490d6d1",
        source_data_sha256=_SOURCE_DATA_SHA256,
        config_sha256=config_sha256,
        signal_bar_open_utc=datetime(2026, 7, 20, 23, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 21, tzinfo=UTC),
        decision_not_before_utc=decision_not_before_utc,
        expires_at_utc=datetime(2026, 7, 21, 1, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )


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
    target: TargetPositionIntent | None = None,
    side: str = "buy",
    order_type: str = "post_only_limit",
    exchange_fee_bps: str = "5",
    market_snapshot_sha256: str | None = None,
) -> PaperOrderDecision:
    quote = _quote()
    target = target or _target()
    return PaperOrderDecision(
        target_intent_id=target.intent_id,
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
    target: TargetPositionIntent | None = None,
    decision: PaperOrderDecision | None = None,
    created_at_utc: datetime | str = datetime(
        2026,
        7,
        21,
        0,
        0,
        0,
        450_000,
        tzinfo=UTC,
    ),
    expires_at_utc: datetime | str = datetime(2026, 7, 21, 0, 0, 2, tzinfo=UTC),
    maximum_quote_age_ms: int = 250,
    limit_price: str = "66113.8",
) -> PaperPostOnlyOrderIntent:
    target = target or _target()
    return build_paper_post_only_order_intent(
        decision or _decision(target=target),
        target,
        _quote(),
        created_at_utc=created_at_utc,
        expires_at_utc=expires_at_utc,
        maximum_quote_age_ms=maximum_quote_age_ms,
        limit_price=limit_price,
    )


def test_post_only_order_intent_is_canonical_idempotent_and_reconstructable() -> None:
    target = _target()
    decision = _decision(target=target)
    quote = _quote()
    intent = _intent(target=target, decision=decision)
    replayed = PaperPostOnlyOrderIntent.from_json_bytes(intent.to_json_bytes())

    assert replayed == intent
    assert replayed.time_in_force == "post_only"
    assert replayed.exchange_fee_bps == "5"
    assert replayed.limit_price == quote.bid_price
    assert replayed.target_intent_id == target.intent_id
    assert replayed.quote_snapshot_id == quote.snapshot_id
    replayed.assert_reconstructs(decision, target, quote)

    payload = json.loads(replayed.to_json_bytes())
    assert "spread_bps" not in payload
    assert "slippage_bps" not in payload
    assert "market_impact_bps" not in payload
    assert "latency_ms" not in payload


def test_timezone_equivalent_inputs_preserve_order_intent_identity() -> None:
    utc_intent = _intent()
    adelaide = timezone(timedelta(hours=9, minutes=30))
    offset_intent = _intent(
        created_at_utc=datetime(2026, 7, 21, 9, 30, 0, 450_000, tzinfo=adelaide),
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


def test_post_only_order_intent_rejects_pre_activation_quote() -> None:
    target = _target(decision_not_before_utc=datetime(2026, 7, 21, 0, 0, 0, 350_000, tzinfo=UTC))

    with pytest.raises(ValueError, match="predates target-intent activation"):
        _intent(target=target, decision=_decision(target=target))


def test_post_only_order_intent_requires_exact_decision_quote_target_and_fee() -> None:
    target = _target()
    with pytest.raises(ValueError, match="planned post-only limit decision"):
        _intent(target=target, decision=_decision(target=target, order_type="market"))

    with pytest.raises(ValueError, match="exactly 5 bps"):
        _intent(target=target, decision=_decision(target=target, exchange_fee_bps="6"))

    with pytest.raises(ValueError, match="exact execution quote"):
        _intent(
            target=target,
            decision=_decision(target=target, market_snapshot_sha256="9" * 64),
        )

    other_target = _target(config_sha256="2" * 64)
    with pytest.raises(ValueError, match="exact target intent"):
        _intent(target=other_target, decision=_decision(target=target))


def test_post_only_order_intent_cannot_outlive_or_postdate_target() -> None:
    target = _target()
    with pytest.raises(ValueError, match="expired"):
        _intent(target=target, created_at_utc=target.expires_at_utc)

    with pytest.raises(ValueError, match="cannot outlive"):
        _intent(
            target=target,
            expires_at_utc=target.expires_at_utc + timedelta(microseconds=1),
        )


def test_post_only_sell_requires_limit_at_or_above_reference_ask() -> None:
    target = _target()
    decision = _decision(target=target, side="sell")
    accepted = _intent(target=target, decision=decision, limit_price="66114")
    assert accepted.side == "sell"

    with pytest.raises(ValueError, match="at or above the reference ask"):
        _intent(target=target, decision=decision, limit_price="66113.9")
