from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample
from gpt_quant.okx_order_constraints import (
    validate_okx_spot_limit_order_constraints,
    validate_okx_spot_order_quantity,
)

_INSTRUMENT_FIXTURE_DIR = (
    Path(__file__).parent / "fixtures/okx/public_instruments_btc_usdt_20251125"
)
_BOOK_FIXTURE_DIR = Path(__file__).parent / "fixtures/okx/order-book-btc-usdt-docs-20210826"
_INSTRUMENT_RESPONSE_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_BOOK_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"


def _real_instrument_response() -> bytes:
    response = (_INSTRUMENT_FIXTURE_DIR / "response.json").read_bytes()
    metadata = json.loads(
        (_INSTRUMENT_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8")
    )
    assert metadata["fixture_sha256"] == _INSTRUMENT_RESPONSE_SHA256
    assert hashlib.sha256(response).hexdigest() == _INSTRUMENT_RESPONSE_SHA256
    return response


def _real_limit_price() -> str:
    response = (_BOOK_FIXTURE_DIR / "response.json").read_bytes()
    metadata = json.loads((_BOOK_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["response_sha256"] == _BOOK_RESPONSE_SHA256
    assert hashlib.sha256(response).hexdigest() == _BOOK_RESPONSE_SHA256
    payload = json.loads(response)
    return payload["data"][0]["asks"][0][0]


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _snapshot(*, instrument_request_round_trip: timedelta):
    started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    received = started + instrument_request_round_trip
    server_started = received + timedelta(milliseconds=1)
    server_received = server_started + timedelta(milliseconds=100)
    midpoint = server_started + (server_received - server_started) / 2
    sample = OKXServerTimeSample(
        base_url="https://www.okx.com",
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp(server_started),
        local_response_received_utc=pd.Timestamp(server_received),
        server_time_utc=pd.Timestamp(midpoint),
        round_trip_seconds=0.1,
        midpoint_clock_skew_seconds=0.0,
    )
    snapshot = fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        server_time_sample=sample,
        get_bytes=lambda _url, _timeout: _real_instrument_response(),
        now=_clock(started, received),
    )
    return snapshot, server_received + timedelta(milliseconds=1)


def test_slow_instrument_response_cannot_appear_fresh_at_order_submission() -> None:
    snapshot, submitted_at = _snapshot(instrument_request_round_trip=timedelta(seconds=2.5))

    assert submitted_at - snapshot.response_received_utc < timedelta(milliseconds=1_000)
    assert (
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=submitted_at,
            maximum_snapshot_age_ms=1_000,
            base_quantity="0.00001",
            maximum_instrument_request_round_trip_seconds=3.0,
        )
        == "0.00001"
    )

    with pytest.raises(ValueError, match="instrument request round trip exceeds"):
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=submitted_at,
            maximum_snapshot_age_ms=1_000,
            base_quantity="0.00001",
        )

    with pytest.raises(ValueError, match="instrument request round trip exceeds"):
        validate_okx_spot_limit_order_constraints(
            snapshot,
            submitted_at_utc=submitted_at,
            maximum_snapshot_age_ms=1_000,
            base_quantity="0.00001",
            limit_price=_real_limit_price(),
        )


def test_existing_fast_constraint_calls_preserve_default_api() -> None:
    snapshot, submitted_at = _snapshot(instrument_request_round_trip=timedelta(milliseconds=125))

    assert (
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=submitted_at,
            maximum_snapshot_age_ms=1_000,
            base_quantity="0.00001",
        )
        == "0.00001"
    )
    assert validate_okx_spot_limit_order_constraints(
        snapshot,
        submitted_at_utc=submitted_at,
        maximum_snapshot_age_ms=1_000,
        base_quantity="0.00001",
        limit_price=_real_limit_price(),
    ) == ("0.00001", "41006.8")


@pytest.mark.parametrize("maximum_round_trip", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_instrument_request_round_trip_policy_fails_closed(
    maximum_round_trip: float,
) -> None:
    snapshot, submitted_at = _snapshot(instrument_request_round_trip=timedelta(milliseconds=125))

    with pytest.raises(ValueError, match="positive finite number"):
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=submitted_at,
            maximum_snapshot_age_ms=1_000,
            base_quantity="0.00001",
            maximum_instrument_request_round_trip_seconds=maximum_round_trip,
        )
