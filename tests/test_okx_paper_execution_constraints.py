from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample
from gpt_quant.okx_order_constraints import validate_okx_paper_execution_attempt_constraints
from gpt_quant.paper_execution_attempt import record_paper_execution_attempt

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx"
_INSTRUMENT_DIR = _FIXTURE_ROOT / "public_instruments_btc_usdt_20251125"
_BOOK_DIR = _FIXTURE_ROOT / "order-book-btc-usdt-docs-20210826"
_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _instrument_snapshot():
    raw = (_INSTRUMENT_DIR / "response.json").read_bytes()
    metadata = json.loads((_INSTRUMENT_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["fixture_sha256"] == _INSTRUMENT_SHA256
    assert hashlib.sha256(raw).hexdigest() == _INSTRUMENT_SHA256

    started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    received = started + timedelta(milliseconds=125)
    server_started = received + timedelta(milliseconds=1)
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
        now=_clock(started, received),
    )


def _quote(snapshot_sha256: str = _INSTRUMENT_SHA256) -> ExecutionQuoteSnapshot:
    raw = (_BOOK_DIR / "response.json").read_bytes()
    metadata = json.loads((_BOOK_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["response_sha256"] == _BOOK_SHA256
    assert metadata["instrument_snapshot_sha256"] == _INSTRUMENT_SHA256
    assert hashlib.sha256(raw).hexdigest() == _BOOK_SHA256
    book = json.loads(raw)["data"][0]
    bid_price, bid_quantity, *_ = book["bids"][0]
    ask_price, ask_quantity, *_ = book["asks"][0]
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime(2026, 7, 24, 0, 0, 0, 300_000, tzinfo=UTC),
        received_at_utc=datetime(2026, 7, 24, 0, 0, 0, 350_000, tzinfo=UTC),
        bid_price=bid_price,
        bid_quantity=bid_quantity,
        ask_price=ask_price,
        ask_quantity=ask_quantity,
        source_response_sha256=_BOOK_SHA256,
        instrument_snapshot_sha256=snapshot_sha256,
    )


def _binding(quote: ExecutionQuoteSnapshot):
    intent = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-five-bps",
        strategy_revision="cdf46e914ef15020ab864997d310ba048c13ae62",
        source_data_sha256=_SOURCE_DATA_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2026, 7, 22, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 23, tzinfo=UTC),
        decision_not_before_utc=datetime(2026, 7, 24, 0, 0, 0, 200_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 25, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    return bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 24, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=500,
    )


def _attempt(
    quote: ExecutionQuoteSnapshot,
    *,
    requested: str,
    outcome: str,
    filled: str,
    average_fill_price: str | None = None,
):
    return record_paper_execution_attempt(
        _binding(quote),
        quote,
        submitted_at_utc=datetime(2026, 7, 24, 0, 0, 0, 450_000, tzinfo=UTC),
        outcome_at_utc=datetime(2026, 7, 24, 0, 0, 0, 500_000, tzinfo=UTC),
        side="buy",
        requested_base_quantity=requested,
        outcome=outcome,
        filled_base_quantity=filled,
        average_fill_price=(
            average_fill_price
            if average_fill_price is not None
            else quote.ask_price if Decimal(filled) > 0 else "0"
        ),
        reason_code="paper-touch-fill" if Decimal(filled) > 0 else "paper-accepted",
    )


def test_real_okx_attempt_is_bound_to_instrument_lot_and_visible_touch_capacity() -> None:
    snapshot = _instrument_snapshot()
    quote = _quote(snapshot.raw_response_sha256)
    attempt = _attempt(quote, requested="0.1", outcome="filled", filled="0.1")

    validate_okx_paper_execution_attempt_constraints(
        snapshot,
        quote,
        attempt,
        maximum_snapshot_age_ms=1_000,
    )


@pytest.mark.parametrize(
    ("requested", "outcome", "filled", "error"),
    [
        (
            "0.100000005",
            "accepted",
            "0",
            "base_quantity is not an exact multiple of the OKX lot size",
        ),
        (
            "0.1",
            "partial",
            "0.040000005",
            "filled_base_quantity is not an exact multiple of the OKX lot size",
        ),
        (
            "0.7",
            "partial",
            "0.60038922",
            "exceeds the supplied same-side top-of-book quantity",
        ),
    ],
)
def test_okx_attempt_gate_rejects_unexecutable_quantity_evidence(
    requested: str,
    outcome: str,
    filled: str,
    error: str,
) -> None:
    snapshot = _instrument_snapshot()
    quote = _quote(snapshot.raw_response_sha256)
    attempt = _attempt(quote, requested=requested, outcome=outcome, filled=filled)

    with pytest.raises(ValueError, match=error):
        validate_okx_paper_execution_attempt_constraints(
            snapshot,
            quote,
            attempt,
            maximum_snapshot_age_ms=1_000,
        )


def test_okx_attempt_gate_rejects_a_different_instrument_snapshot() -> None:
    snapshot = _instrument_snapshot()
    quote = _quote("0" * 64)
    attempt = _attempt(quote, requested="0.1", outcome="filled", filled="0.1")

    with pytest.raises(ValueError, match="does not reference the supplied OKX instrument"):
        validate_okx_paper_execution_attempt_constraints(
            snapshot,
            quote,
            attempt,
            maximum_snapshot_age_ms=1_000,
        )


def test_okx_attempt_gate_rejects_off_tick_average_fill_price() -> None:
    snapshot = _instrument_snapshot()
    quote = _quote(snapshot.raw_response_sha256)
    attempt = _attempt(
        quote,
        requested="0.1",
        outcome="filled",
        filled="0.1",
        average_fill_price="41006.85",
    )

    with pytest.raises(
        ValueError,
        match="average_fill_price is not an exact multiple of the OKX tick size",
    ):
        validate_okx_paper_execution_attempt_constraints(
            snapshot,
            quote,
            attempt,
            maximum_snapshot_age_ms=1_000,
        )
