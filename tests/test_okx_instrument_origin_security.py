from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import BaseHandler, Request, addinfourl
from urllib.request import build_opener as std_build_opener

import pandas as pd
import pytest

import gpt_quant.okx_instruments as okx_instruments
from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample

_FIXTURE_DIR = Path(__file__).parent / "fixtures/okx/public_instruments_btc_usdt_20251125"
_EXPECTED_RESPONSE_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"


def _real_okx_response_bytes() -> bytes:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    response = (_FIXTURE_DIR / "response.json").read_bytes()
    assert metadata["fixture_sha256"] == _EXPECTED_RESPONSE_SHA256
    assert hashlib.sha256(response).hexdigest() == _EXPECTED_RESPONSE_SHA256
    return response


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _server_time_sample(*, instrument_received: datetime, base_url: str) -> OKXServerTimeSample:
    local_started = instrument_received + timedelta(milliseconds=1)
    local_received = local_started + timedelta(milliseconds=100)
    midpoint = local_started + (local_received - local_started) / 2
    return OKXServerTimeSample(
        base_url=base_url,
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp(local_started),
        local_response_received_utc=pd.Timestamp(local_received),
        server_time_utc=pd.Timestamp(midpoint),
        round_trip_seconds=0.1,
        midpoint_clock_skew_seconds=0.0,
    )


@pytest.mark.parametrize(
    "base_url",
    [
        "http://www.okx.com",
        "https://127.0.0.1",
        "https://169.254.169.254",
        "https://localhost",
        "https://www.okx.com@evil.example",
        "https://www.okx.com.evil.example",
        "https://www.okx.com:443",
        "https://www.okx.com:",
        "https://.okx.com",
        "https://foo..okx.com",
        "https://www.okx.com/api",
        "https://www.okx.com?redirect=https://169.254.169.254",
        "https://www.okx.com#fragment",
    ],
)
def test_fetch_okx_spot_instrument_rejects_untrusted_origin_before_io(base_url: str) -> None:
    started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    received = started + timedelta(milliseconds=125)

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("untrusted origin reached network or clock boundary")

    with pytest.raises(ValueError, match="trusted public OKX HTTPS origin"):
        fetch_okx_spot_instrument_snapshot(
            inst_id="BTC-USDT",
            base_url=base_url,
            server_time_sample=_server_time_sample(
                instrument_received=received,
                base_url=base_url,
            ),
            get_bytes=forbidden,
            now=forbidden,
        )


class _RedirectingHTTPSHandler(BaseHandler):
    handler_order = 100

    def https_open(self, request: Request):
        headers = Message()
        headers["Location"] = "https://169.254.169.254/latest/meta-data/"
        response = addinfourl(BytesIO(b""), headers, request.full_url, 302)
        response.msg = "Found"
        return response


def test_default_instrument_transport_rejects_cross_origin_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def build_redirecting_opener(*handlers: object):
        return std_build_opener(*handlers, _RedirectingHTTPSHandler())

    monkeypatch.setattr(okx_instruments, "build_opener", build_redirecting_opener)
    url = "https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT"

    with pytest.raises(HTTPError) as exc_info:
        okx_instruments._default_raw_bytes_getter(url, 1.0)

    assert exc_info.value.code == 302
    assert exc_info.value.geturl() == url


@pytest.mark.parametrize(
    ("base_url", "normalized_base_url"),
    [
        ("https://www.okx.com/", "https://www.okx.com"),
        ("https://tr.okx.com/", "https://tr.okx.com"),
    ],
)
def test_trusted_origin_preserves_exact_real_instrument_response(
    base_url: str,
    normalized_base_url: str,
) -> None:
    started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    received = started + timedelta(milliseconds=125)
    requests: list[str] = []
    response = _real_okx_response_bytes()

    snapshot = fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        base_url=base_url,
        server_time_sample=_server_time_sample(
            instrument_received=received,
            base_url=normalized_base_url,
        ),
        get_bytes=lambda url, _timeout: requests.append(url) or response,
        now=_clock(started, received),
    )

    assert requests == [
        f"{normalized_base_url}/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT"
    ]
    assert snapshot.base_url == normalized_base_url
    assert snapshot.raw_response_json == response
    assert snapshot.raw_response_sha256 == _EXPECTED_RESPONSE_SHA256
