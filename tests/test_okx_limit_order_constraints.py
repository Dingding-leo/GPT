from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.okx_instruments import (
    OKXSpotInstrumentSnapshot,
    fetch_okx_spot_instrument_snapshot,
)
from gpt_quant.okx_live import OKXServerTimeSample
from gpt_quant.okx_order_constraints import validate_okx_spot_limit_order_constraints

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx"
_INSTRUMENT_DIR = _FIXTURE_ROOT / "public_instruments_btc_usdt_20251125"
_BOOK_DIR = _FIXTURE_ROOT / "order-book-btc-usdt-docs-20210826"
_EXPECTED_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_EXPECTED_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _instrument_snapshot() -> OKXSpotInstrumentSnapshot:
    raw = (_INSTRUMENT_DIR / "response.json").read_bytes()
    metadata = json.loads((_INSTRUMENT_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["fixture_sha256"] == _EXPECTED_INSTRUMENT_SHA256
    assert hashlib.sha256(raw).hexdigest() == _EXPECTED_INSTRUMENT_SHA256

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


def _real_ask_price() -> str:
    raw = (_BOOK_DIR / "response.json").read_bytes()
    metadata = json.loads((_BOOK_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["response_sha256"] == _EXPECTED_BOOK_SHA256
    assert metadata["instrument_snapshot_sha256"] == _EXPECTED_INSTRUMENT_SHA256
    assert hashlib.sha256(raw).hexdigest() == _EXPECTED_BOOK_SHA256
    payload = json.loads(raw)
    return payload["data"][0]["asks"][0][0]


def test_real_okx_limit_price_must_align_to_the_exchange_tick() -> None:
    snapshot = _instrument_snapshot()
    submitted_at = snapshot.server_time_response_received_utc + timedelta(milliseconds=1)
    real_ask_price = _real_ask_price()

    assert validate_okx_spot_limit_order_constraints(
        snapshot,
        submitted_at_utc=submitted_at,
        maximum_snapshot_age_ms=1_000,
        base_quantity=snapshot.minimum_order_size_base,
        limit_price=real_ask_price,
    ) == (snapshot.minimum_order_size_base, real_ask_price)

    off_tick_price = format(
        Decimal(real_ask_price) + snapshot.tick_size_decimal / Decimal(2),
        "f",
    )
    with pytest.raises(ValueError, match="exact multiple of the OKX tick size"):
        validate_okx_spot_limit_order_constraints(
            snapshot,
            submitted_at_utc=submitted_at,
            maximum_snapshot_age_ms=1_000,
            base_quantity=snapshot.minimum_order_size_base,
            limit_price=off_tick_price,
        )

    with pytest.raises(ValueError, match="canonical"):
        validate_okx_spot_limit_order_constraints(
            snapshot,
            submitted_at_utc=submitted_at,
            maximum_snapshot_age_ms=1_000,
            base_quantity=snapshot.minimum_order_size_base,
            limit_price=f"{real_ask_price}0",
        )
