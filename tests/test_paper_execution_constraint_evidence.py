from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample
from gpt_quant.paper_execution_attempt import record_paper_execution_attempt
from gpt_quant.paper_execution_constraint_evidence import (
    OKXPaperExecutionConstraintEvidence,
    record_okx_paper_execution_constraint_evidence,
)

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx"
_INSTRUMENT_DIR = _FIXTURE_ROOT / "public_instruments_btc_usdt_20251125"
_BOOK_DIR = _FIXTURE_ROOT / "order-book-btc-usdt-docs-20210826"
_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"
_REVISION = "c26473cc2009b0b12aff47c3fa7235a6432eeacc"


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _instrument_snapshot():
    raw = (_INSTRUMENT_DIR / "response.json").read_bytes()
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


def _attempt(quote: ExecutionQuoteSnapshot):
    intent = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-five-bps",
        strategy_revision=_REVISION,
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
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 24, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=500,
    )
    return record_paper_execution_attempt(
        binding,
        quote,
        submitted_at_utc=datetime(2026, 7, 24, 0, 0, 0, 450_000, tzinfo=UTC),
        outcome_at_utc=datetime(2026, 7, 24, 0, 0, 0, 500_000, tzinfo=UTC),
        side="buy",
        requested_base_quantity="0.1",
        outcome="partial",
        filled_base_quantity="0.04",
        average_fill_price=quote.ask_price,
        reason_code="paper-touch-partial",
    )


def test_constraint_policy_is_content_addressed_and_replayable() -> None:
    snapshot = _instrument_snapshot()
    quote = _quote(snapshot.raw_response_sha256)
    attempt = _attempt(quote)

    evidence = record_okx_paper_execution_constraint_evidence(
        snapshot,
        quote,
        attempt,
        maximum_snapshot_age_ms=1_000,
        minimum_paper_quote_notional="1",
    )

    assert evidence.exchange_fee_bps_one_way == "5"
    assert evidence.maximum_snapshot_age_ms == 1_000
    assert evidence.minimum_paper_quote_notional == "1"
    assert evidence.instrument_snapshot_sha256 == _INSTRUMENT_SHA256
    assert evidence.quote_snapshot_id == quote.snapshot_id
    assert evidence.attempt_id == attempt.attempt_id
    assert OKXPaperExecutionConstraintEvidence.from_json_bytes(evidence.to_json_bytes()) == evidence
    evidence.assert_reconstructs(snapshot, quote, attempt)


def test_changing_only_the_minimum_notional_changes_policy_identity() -> None:
    snapshot = _instrument_snapshot()
    quote = _quote(snapshot.raw_response_sha256)
    attempt = _attempt(quote)

    one_usdt = record_okx_paper_execution_constraint_evidence(
        snapshot,
        quote,
        attempt,
        maximum_snapshot_age_ms=1_000,
        minimum_paper_quote_notional="1",
    )
    ten_usdt = record_okx_paper_execution_constraint_evidence(
        snapshot,
        quote,
        attempt,
        maximum_snapshot_age_ms=1_000,
        minimum_paper_quote_notional="10",
    )

    assert one_usdt.evidence_id != ten_usdt.evidence_id
    assert one_usdt.attempt_id == ten_usdt.attempt_id
    assert one_usdt.exchange_fee_bps_one_way == ten_usdt.exchange_fee_bps_one_way == "5"


def test_constraint_evidence_rejects_tampered_or_noncanonical_policy_bytes() -> None:
    snapshot = _instrument_snapshot()
    quote = _quote(snapshot.raw_response_sha256)
    attempt = _attempt(quote)
    evidence = record_okx_paper_execution_constraint_evidence(
        snapshot,
        quote,
        attempt,
        maximum_snapshot_age_ms=1_000,
        minimum_paper_quote_notional="1",
    )

    tampered = evidence.to_json_bytes().replace(
        b'"minimum_paper_quote_notional":"1"',
        b'"minimum_paper_quote_notional":"2"',
    )
    with pytest.raises(ValueError, match="ID does not match"):
        OKXPaperExecutionConstraintEvidence.from_json_bytes(tampered)

    duplicate = evidence.to_json_bytes().replace(
        b"{",
        b'{"maximum_snapshot_age_ms":1000,',
        1,
    )
    with pytest.raises(ValueError, match="JSON is unreadable"):
        OKXPaperExecutionConstraintEvidence.from_json_bytes(duplicate)

    noncanonical = evidence.to_json_bytes().replace(
        b'"minimum_paper_quote_notional":"1"',
        b'"minimum_paper_quote_notional":"1.0"',
    )
    with pytest.raises(ValueError, match="canonical decimal encoding"):
        OKXPaperExecutionConstraintEvidence.from_json_bytes(noncanonical)
