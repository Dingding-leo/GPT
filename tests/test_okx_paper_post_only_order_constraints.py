from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.okx_instruments import (
    OKXSpotInstrumentSnapshot,
    fetch_okx_spot_instrument_snapshot,
)
from gpt_quant.okx_live import OKXServerTimeSample
from gpt_quant.okx_order_constraints import (
    validate_okx_paper_post_only_order_intent_constraints,
)
from gpt_quant.paper_order_decision import PaperOrderDecision
from gpt_quant.paper_post_only_order_intent import build_paper_post_only_order_intent

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx"
_INSTRUMENT_DIR = _FIXTURE_ROOT / "public_instruments_btc_usdt_20251125"
_BOOK_DIR = _FIXTURE_ROOT / "order-book-btc-usdt-docs-20210826"
_EXPECTED_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_EXPECTED_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _instrument_snapshot() -> OKXSpotInstrumentSnapshot:
    raw = (_INSTRUMENT_DIR / "response.json").read_bytes()
    metadata = json.loads((_INSTRUMENT_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["fixture_sha256"] == _EXPECTED_INSTRUMENT_SHA256
    assert hashlib.sha256(raw).hexdigest() == _EXPECTED_INSTRUMENT_SHA256

    request_started = datetime(2026, 7, 21, 0, 0, 0, 100_000, tzinfo=UTC)
    response_received = datetime(2026, 7, 21, 0, 0, 0, 225_000, tzinfo=UTC)
    server_started = datetime(2026, 7, 21, 0, 0, 0, 226_000, tzinfo=UTC)
    server_received = datetime(2026, 7, 21, 0, 0, 0, 326_000, tzinfo=UTC)
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


def _quote(snapshot: OKXSpotInstrumentSnapshot) -> ExecutionQuoteSnapshot:
    raw = (_BOOK_DIR / "response.json").read_bytes()
    metadata = json.loads((_BOOK_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["response_sha256"] == _EXPECTED_BOOK_SHA256
    assert metadata["instrument_snapshot_sha256"] == _EXPECTED_INSTRUMENT_SHA256
    assert hashlib.sha256(raw).hexdigest() == _EXPECTED_BOOK_SHA256
    book = json.loads(raw)["data"][0]
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id=snapshot.instrument_id,
        observed_at_utc=datetime(2026, 7, 21, 0, 0, 0, 300_000, tzinfo=UTC),
        received_at_utc=datetime(2026, 7, 21, 0, 0, 0, 350_000, tzinfo=UTC),
        bid_price=book["bids"][0][0],
        bid_quantity=book["bids"][0][1],
        ask_price=book["asks"][0][0],
        ask_quantity=book["asks"][0][1],
        source_response_sha256=_EXPECTED_BOOK_SHA256,
        instrument_snapshot_sha256=snapshot.raw_response_sha256,
    )


def _intent(*, base_quantity: str, limit_price: str):
    snapshot = _instrument_snapshot()
    quote = _quote(snapshot)
    target = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1H",
        strategy_id="canonical-one-hour-five-bps",
        strategy_revision="e5e7ef22a23e6673c0183f47c0398f6af490d6d1",
        source_data_sha256=_SOURCE_DATA_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2026, 7, 20, 23, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 21, tzinfo=UTC),
        decision_not_before_utc=datetime(2026, 7, 21, 0, 0, 0, 200_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 21, 1, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    spread_bps = format(quote.spread_bps, "f").rstrip("0").rstrip(".")
    decision = PaperOrderDecision(
        target_intent_id=target.intent_id,
        instrument_id=target.instrument_id,
        decided_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        market_observed_at_utc=quote.observed_at_utc,
        outcome="planned",
        reason_code="pretrade_passed",
        order_type="post_only_limit",
        side="buy",
        base_quantity=base_quantity,
        instrument_snapshot_sha256=snapshot.raw_response_sha256,
        market_snapshot_sha256=quote.snapshot_id,
        portfolio_state_before_sha256="4" * 64,
        risk_state_before_sha256="5" * 64,
        exchange_fee_bps="5",
        spread_bps=spread_bps,
        slippage_bps="0",
        market_impact_bps="0",
        latency_ms=50,
    )
    intent = build_paper_post_only_order_intent(
        decision,
        target,
        quote,
        created_at_utc=datetime(2026, 7, 21, 0, 0, 0, 450_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 21, 0, 0, 2, tzinfo=UTC),
        maximum_quote_age_ms=250,
        limit_price=limit_price,
    )
    return snapshot, quote, intent


def test_real_okx_maker_intent_passes_exact_lot_tick_and_notional_constraints() -> None:
    snapshot = _instrument_snapshot()
    quote = _quote(snapshot)
    snapshot, quote, intent = _intent(
        base_quantity="0.001",
        limit_price=quote.bid_price,
    )

    validate_okx_paper_post_only_order_intent_constraints(
        snapshot,
        quote,
        intent,
        maximum_snapshot_age_ms=1_000,
        minimum_paper_quote_notional="10",
    )


@pytest.mark.parametrize(
    ("base_quantity", "limit_price", "minimum_notional", "message"),
    [
        ("0.000010005", "41006.3", "0.1", "exact multiple of the OKX lot size"),
        ("0.001", "41006.25", "10", "exact multiple of the OKX tick size"),
        ("0.00001", "41006.3", "10", "below the declared paper minimum"),
    ],
)
def test_generic_maker_intent_cannot_bypass_okx_order_constraints(
    base_quantity: str,
    limit_price: str,
    minimum_notional: str,
    message: str,
) -> None:
    snapshot, quote, intent = _intent(
        base_quantity=base_quantity,
        limit_price=limit_price,
    )

    with pytest.raises(ValueError, match=message):
        validate_okx_paper_post_only_order_intent_constraints(
            snapshot,
            quote,
            intent,
            maximum_snapshot_age_ms=1_000,
            minimum_paper_quote_notional=minimum_notional,
        )
