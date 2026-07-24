from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample

_FIXTURE_DIR = Path(__file__).parent / "fixtures/okx/public_instruments_btc_usdt_20251125"
_FIXTURE_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"


def _real_okx_response_bytes() -> bytes:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    response_bytes = (_FIXTURE_DIR / "response.json").read_bytes()
    assert metadata["fixture_sha256"] == _FIXTURE_SHA256
    assert hashlib.sha256(response_bytes).hexdigest() == _FIXTURE_SHA256
    return response_bytes


def test_nanosecond_server_time_survives_snapshot_revalidation() -> None:
    instrument_started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    instrument_received = instrument_started + timedelta(milliseconds=125)
    server_started = pd.Timestamp("2026-07-24T00:00:00.126000123Z")
    server_received = pd.Timestamp("2026-07-24T00:00:00.226000579Z")
    exchange_observed = pd.Timestamp("2026-07-24T00:00:00.176000387Z")
    midpoint = server_started + (server_received - server_started) / 2
    sample = OKXServerTimeSample(
        base_url="https://www.okx.com",
        endpoint="/api/v5/public/time",
        local_request_started_utc=server_started,
        local_response_received_utc=server_received,
        server_time_utc=exchange_observed,
        round_trip_seconds=(server_received - server_started).total_seconds(),
        midpoint_clock_skew_seconds=(exchange_observed - midpoint).total_seconds(),
    )
    clock_values = iter((instrument_started, instrument_received))

    snapshot = fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        server_time_sample=sample,
        get_bytes=lambda _url, _timeout: _real_okx_response_bytes(),
        now=lambda: next(clock_values),
    )

    assert snapshot.server_time_request_started_utc == server_started
    assert snapshot.server_time_response_received_utc == server_received
    assert snapshot.exchange_observed_at_utc == exchange_observed
    metadata = json.loads(snapshot.metadata_bytes())
    assert metadata["server_time_request_started_utc"] == "2026-07-24T00:00:00.126000123Z"
    assert metadata["server_time_response_received_utc"] == "2026-07-24T00:00:00.226000579Z"
    assert metadata["exchange_observed_at_utc"] == "2026-07-24T00:00:00.176000387Z"
