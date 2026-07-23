from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample

_FIXTURE = Path(__file__).parent / "fixtures/okx/public_instruments_btc_usdt_20251125/response.json"


def _payload() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_bytes())


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _fetch(payload: dict[str, Any]) -> None:
    started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    received = started + timedelta(milliseconds=1)
    local_started = received + timedelta(milliseconds=1)
    local_received = local_started + timedelta(milliseconds=100)
    midpoint = local_started + (local_received - local_started) / 2
    sample = OKXServerTimeSample(
        base_url="https://www.okx.com",
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp(local_started),
        local_response_received_utc=pd.Timestamp(local_received),
        server_time_utc=pd.Timestamp(midpoint),
        round_trip_seconds=0.1,
        midpoint_clock_skew_seconds=0.0,
    )
    fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        server_time_sample=sample,
        get_json=lambda _url, _timeout: deepcopy(payload),
        now=_clock(started, received),
    )


@pytest.mark.parametrize("malformed", ["1_000", "١", "１", ".1", "1."])
def test_malformed_okx_decimal_constraints_fail_closed(malformed: str) -> None:
    payload = _payload()
    payload["data"][0]["tickSz"] = malformed

    with pytest.raises(ValueError, match="tickSz must be a plain positive decimal string"):
        _fetch(payload)
