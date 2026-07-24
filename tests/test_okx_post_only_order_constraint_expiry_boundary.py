from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample
from gpt_quant.okx_post_only_order_constraints import (
    validate_okx_paper_post_only_order_intent_constraints,
)
from gpt_quant.paper_order_decision import PaperOrderDecision
from gpt_quant.paper_post_only_order_intent import build_paper_post_only_order_intent

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx"
_INSTRUMENT_RESPONSE = (
    _FIXTURE_ROOT / "public_instruments_btc_usdt_20251125" / "response.json"
)
_BOOK_RESPONSE = _FIXTURE_ROOT / "order-book-btc-usdt-docs-20210826" / "response.json"
_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _instrument_snapshot():
    raw = _INSTRUMENT_RESPONSE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _INSTRUMENT_SHA256

    request_started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    response_received = request_started + timedelta(milliseconds=125)
    server_started = response_received + timedelta(milliseconds=1)
    server_received = server_started + timedelta(milliseconds=100)
    server_time = server_started + (server_received - server_started) / 2
    sample = OKXServerTimeSample(
        base_url="https://www.okx.com",
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp(server_started),
        local_response_received_utc=pd.Timestamp(server_received),
        server_time_utc=pd.Timestamp(server_time),
        round_trip_seconds=0.1,
        midpoint_clock_skew_seconds=0.0,
    )
    return fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        server_time_sample=sample,
        get_bytes=lambda _url, _timeout: raw,
        now=_clock(request_started, response_received),
    )


def _evidence():
    raw = _BOOK_RESPONSE.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == _BOOK_SHA256
    book = json.loads(raw)["data"][0]
    bid_price, bid_quantity, *_ = book["bids"][0]
    ask_price, ask_quantity, *_ = book["asks"][0]
    quote = ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime(2026, 7, 24, 0, 0, 0, 300_000, tzinfo=UTC),
        received_at_utc=datetime(2026, 7, 24, 0, 0, 0, 350_000, tzinfo=UTC),
        bid_price=bid_price,
        bid_quantity=bid_quantity,
        ask_price=ask_price,
        ask_quantity=ask_quantity,
        source_response_sha256=_BOOK_SHA256,
        instrument_snapshot_sha256=_INSTRUMENT_SHA256,
    )
    target = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1H",
        strategy_id="canonical-one-hour-five-bps",
        strategy_revision="e5e7ef22a23e6673c0183f47c0398f6af490d6d1",
        source_data_sha256=_SOURCE_DATA_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2026, 7, 23, 23, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 24, 0, tzinfo=UTC),
        decision_not_before_utc=datetime(2026, 7, 24, 0, 0, 0, 200_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 24, 1, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    decision = PaperOrderDecision(
        target_intent_id=target.intent_id,
        instrument_id="BTC-USDT",
        decided_at_utc=datetime(2026, 7, 24, 0, 0, 0, 400_000, tzinfo=UTC),
        market_observed_at_utc=quote.observed_at_utc,
        outcome="planned",
        reason_code="pretrade_passed",
        order_type="post_only_limit",
        side="buy",
        base_quantity="0.001",
        instrument_snapshot_sha256=quote.instrument_snapshot_sha256,
        market_snapshot_sha256=quote.snapshot_id,
        portfolio_state_before_sha256="4" * 64,
        risk_state_before_sha256="5" * 64,
        exchange_fee_bps="5",
        spread_bps="0.12193155715988921544729068924406665145762840994843",
        slippage_bps="0",
        market_impact_bps="0",
        latency_ms=50,
    )
    return target, decision, quote


def _intent(*, expires_at_utc: datetime):
    target, decision, quote = _evidence()
    intent = build_paper_post_only_order_intent(
        decision,
        target,
        quote,
        created_at_utc=datetime(2026, 7, 24, 0, 0, 0, 450_000, tzinfo=UTC),
        expires_at_utc=expires_at_utc,
        maximum_quote_age_ms=250,
        limit_price=quote.bid_price,
    )
    return target, decision, quote, intent


def test_snapshot_freshness_uses_exclusive_maker_intent_expiry() -> None:
    snapshot = _instrument_snapshot()
    freshness_deadline = datetime(2026, 7, 24, 0, 0, 1, 125_000, tzinfo=UTC)
    target, decision, quote, accepted = _intent(
        expires_at_utc=freshness_deadline + timedelta(microseconds=1)
    )

    validate_okx_paper_post_only_order_intent_constraints(
        snapshot,
        quote,
        accepted,
        decision=decision,
        target=target,
        maximum_snapshot_age_ms=1_000,
        minimum_paper_quote_notional="1",
    )

    target, decision, quote, rejected = _intent(
        expires_at_utc=freshness_deadline + timedelta(microseconds=2)
    )
    with pytest.raises(
        ValueError,
        match="outlives the supplied OKX instrument constraint",
    ):
        validate_okx_paper_post_only_order_intent_constraints(
            snapshot,
            quote,
            rejected,
            decision=decision,
            target=target,
            maximum_snapshot_age_ms=1_000,
            minimum_paper_quote_notional="1",
        )
