from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.okx_execution_quote import fetch_okx_top_of_book
from gpt_quant.okx_execution_quote_replay import ReconstructableOKXTopOfBookEvidence

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "order-book-btc-usdt-docs-20210826"
_RESPONSE_PATH = _FIXTURE_DIR / "response.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_EXPECTED_SERVER_TIME_RESPONSE_SHA256 = (
    "2ab44b9abd247acb72cf79b22b30e14c4e80cc00a96384a4535b31a37f6dfeb0"
)
_INSTRUMENT_SNAPSHOT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"


def _fixture_response() -> bytes:
    response = _RESPONSE_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["endpoint"] == "/api/v5/market/books"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["depth"] == 1
    assert metadata["source_kind"] == "official_documentation_response_example"
    assert metadata["response_sha256"] == _EXPECTED_RESPONSE_SHA256
    assert metadata["instrument_snapshot_sha256"] == _INSTRUMENT_SNAPSHOT_SHA256
    assert hashlib.sha256(response).hexdigest() == _EXPECTED_RESPONSE_SHA256
    return response


def _clock(*values: str):
    timestamps: Iterator[datetime] = iter(
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC) for value in values
    )
    return lambda: next(timestamps)


def _server_time_response(expected_ms: str) -> bytes:
    return f'{{"code":"0","msg":"","data":[{{"ts":"{expected_ms}"}}]}}'.encode()


def _server_time_getter(expected_ms: str):
    response = _server_time_response(expected_ms)

    def fake_getter(url: str, timeout: float) -> bytes:
        assert url == "https://test.okx.com/api/v5/public/time"
        assert timeout == 20.0
        return response

    return fake_getter


def test_fetch_okx_top_of_book_binds_real_public_response_to_exchange_time() -> None:
    requested_urls: list[str] = []

    def fake_books_getter(url: str, timeout: float) -> bytes:
        requested_urls.append(url)
        assert timeout == 20.0
        return _fixture_response()

    observation = fetch_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
        base_url="https://test.okx.com",
        maximum_quote_age_ms=200,
        get_bytes=fake_books_getter,
        get_server_time_bytes=_server_time_getter("1629966436500"),
        now=_clock(
            "2021-08-26T08:27:16.420000Z",
            "2021-08-26T08:27:16.450000Z",
            "2021-08-26T08:27:16.460000Z",
            "2021-08-26T08:27:16.540000Z",
        ),
    )

    assert requested_urls == ["https://test.okx.com/api/v5/market/books?instId=BTC-USDT&sz=1"]
    assert all("account" not in url and "trade" not in url for url in requested_urls)
    assert observation.source_response_sha256 == _EXPECTED_RESPONSE_SHA256
    assert observation.raw_server_time_response_json == _server_time_response("1629966436500")
    assert observation.server_time_response_sha256 == _EXPECTED_SERVER_TIME_RESPONSE_SHA256
    assert observation.exchange_time_observed_utc == datetime(
        2021, 8, 26, 8, 27, 16, 500_000, tzinfo=UTC
    )
    assert observation.request_round_trip_seconds == pytest.approx(0.03)
    assert observation.server_time_endpoint == "/api/v5/public/time"
    assert observation.server_time_request_started_utc == datetime(
        2021, 8, 26, 8, 27, 16, 460_000, tzinfo=UTC
    )
    assert observation.server_round_trip_seconds == pytest.approx(0.08)
    assert observation.midpoint_clock_skew_seconds == pytest.approx(0.0)
    assert observation.max_request_round_trip_seconds == 2.0
    assert observation.max_server_round_trip_seconds == 2.0
    assert observation.max_abs_midpoint_clock_skew_seconds == 5.0

    quote = observation.quote
    assert quote.instrument_id == "BTC-USDT"
    assert quote.observed_at_utc == datetime(2021, 8, 26, 8, 27, 16, 396_000, tzinfo=UTC)
    assert quote.received_at_utc == datetime(2021, 8, 26, 8, 27, 16, 450_000, tzinfo=UTC)
    assert quote.bid_price == "41006.3"
    assert quote.bid_quantity == "0.30178218"
    assert quote.ask_price == "41006.8"
    assert quote.ask_quantity == "0.60038921"
    assert quote.source_response_sha256 == _EXPECTED_RESPONSE_SHA256
    assert quote.instrument_snapshot_sha256 == _INSTRUMENT_SNAPSHOT_SHA256
    assert quote.spread_bps > 0


def test_fresh_quote_survives_bounded_slow_local_clock() -> None:
    observation = fetch_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
        base_url="https://test.okx.com",
        maximum_quote_age_ms=200,
        max_abs_midpoint_clock_skew_seconds=0.2,
        get_bytes=lambda url, timeout: _fixture_response(),
        get_server_time_bytes=_server_time_getter("1629966436500"),
        now=_clock(
            "2021-08-26T08:27:16.320000Z",
            "2021-08-26T08:27:16.350000Z",
            "2021-08-26T08:27:16.360000Z",
            "2021-08-26T08:27:16.440000Z",
        ),
    )

    assert observation.source_response_sha256 == _EXPECTED_RESPONSE_SHA256
    assert observation.midpoint_clock_skew_seconds == pytest.approx(0.1)
    assert observation.quote.observed_at_utc == datetime(
        2021, 8, 26, 8, 27, 16, 396_000, tzinfo=UTC
    )
    assert observation.quote.received_at_utc == (
        observation.response_received_utc
        + timedelta(seconds=observation.midpoint_clock_skew_seconds)
    )

    evidence = ReconstructableOKXTopOfBookEvidence(observation=observation)
    replayed = ReconstructableOKXTopOfBookEvidence.from_json_bytes(evidence.to_json_bytes())
    assert replayed.observation == observation


def test_top_of_book_observation_revalidates_complete_timing_envelope() -> None:
    observation = fetch_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
        base_url="https://test.okx.com",
        maximum_quote_age_ms=200,
        get_bytes=lambda url, timeout: _fixture_response(),
        get_server_time_bytes=_server_time_getter("1629966436500"),
        now=_clock(
            "2021-08-26T08:27:16.420000Z",
            "2021-08-26T08:27:16.450000Z",
            "2021-08-26T08:27:16.460000Z",
            "2021-08-26T08:27:16.540000Z",
        ),
    )

    future_server_receipt = datetime(2026, 7, 23, 21, 0, tzinfo=UTC)
    forged_round_trip = (
        future_server_receipt - observation.server_time_request_started_utc
    ).total_seconds()
    with pytest.raises(ValueError, match="clock skew does not match its timestamps"):
        replace(
            observation,
            server_time_response_received_utc=future_server_receipt,
            server_round_trip_seconds=forged_round_trip,
            max_server_round_trip_seconds=forged_round_trip + 1.0,
            midpoint_clock_skew_seconds=0.0,
        )

    with pytest.raises(ValueError, match="books request round trip exceeds"):
        replace(observation, max_request_round_trip_seconds=0.01)

    with pytest.raises(ValueError, match="does not reproduce the exchange timestamp"):
        replace(
            observation,
            raw_server_time_response_json=_server_time_response("1629966436499"),
        )


def test_fetch_okx_top_of_book_rejects_exchange_stale_response() -> None:
    with pytest.raises(ValueError, match="stale at exchange observation time"):
        fetch_okx_top_of_book(
            instrument_id="BTC-USDT",
            instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
            base_url="https://test.okx.com",
            maximum_quote_age_ms=500,
            get_bytes=lambda url, timeout: _fixture_response(),
            get_server_time_bytes=_server_time_getter("1629966438500"),
            now=_clock(
                "2021-08-26T08:27:16.420000Z",
                "2021-08-26T08:27:16.450000Z",
                "2021-08-26T08:27:18.460000Z",
                "2021-08-26T08:27:18.540000Z",
            ),
        )


def test_fetch_okx_top_of_book_rejects_duplicate_untrusted_response_fields() -> None:
    corrupted = _fixture_response().replace(b'{"code":"0",', b'{"code":"0","code":"0",', 1)

    with pytest.raises(ValueError, match="duplicate field 'code'"):
        fetch_okx_top_of_book(
            instrument_id="BTC-USDT",
            instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
            base_url="https://test.okx.com",
            get_bytes=lambda url, timeout: corrupted,
            get_server_time_bytes=_server_time_getter("1629966436500"),
            now=_clock(
                "2021-08-26T08:27:16.420000Z",
                "2021-08-26T08:27:16.450000Z",
                "2021-08-26T08:27:16.460000Z",
                "2021-08-26T08:27:16.540000Z",
            ),
        )


def test_fetch_okx_top_of_book_rejects_duplicate_server_time_fields() -> None:
    corrupted = b'{"code":"0","msg":"","data":[{"ts":"1629966438500","ts":"1629966436500"}]}'

    with pytest.raises(ValueError, match="duplicate field 'ts'"):
        fetch_okx_top_of_book(
            instrument_id="BTC-USDT",
            instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
            base_url="https://test.okx.com",
            get_bytes=lambda url, timeout: _fixture_response(),
            get_server_time_bytes=lambda url, timeout: corrupted,
            now=_clock(
                "2021-08-26T08:27:16.420000Z",
                "2021-08-26T08:27:16.450000Z",
                "2021-08-26T08:27:16.460000Z",
                "2021-08-26T08:27:16.540000Z",
            ),
        )


def test_fetch_okx_top_of_book_rejects_unexpected_server_time_schema() -> None:
    corrupted = b'{"code":"0","msg":"","data":[{"ts":"1629966436500","extra":"x"}]}'

    with pytest.raises(ValueError, match="server-time object fields do not match"):
        fetch_okx_top_of_book(
            instrument_id="BTC-USDT",
            instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
            base_url="https://test.okx.com",
            get_bytes=lambda url, timeout: _fixture_response(),
            get_server_time_bytes=lambda url, timeout: corrupted,
            now=_clock(
                "2021-08-26T08:27:16.420000Z",
                "2021-08-26T08:27:16.450000Z",
                "2021-08-26T08:27:16.460000Z",
                "2021-08-26T08:27:16.540000Z",
            ),
        )


def test_fetch_okx_top_of_book_rejects_slow_public_response() -> None:
    with pytest.raises(ValueError, match="request round trip exceeds"):
        fetch_okx_top_of_book(
            instrument_id="BTC-USDT",
            instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
            base_url="https://test.okx.com",
            max_request_round_trip_seconds=0.1,
            get_bytes=lambda url, timeout: _fixture_response(),
            get_server_time_bytes=_server_time_getter("1629966436500"),
            now=_clock(
                "2021-08-26T08:27:16.000000Z",
                "2021-08-26T08:27:16.450000Z",
            ),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("max_server_round_trip_seconds", float("inf"), "must be a finite number"),
        ("max_server_round_trip_seconds", float("nan"), "must be a finite number"),
        ("max_server_round_trip_seconds", 0.0, "must be positive"),
        ("max_abs_midpoint_clock_skew_seconds", float("inf"), "must be a finite number"),
        ("max_abs_midpoint_clock_skew_seconds", float("nan"), "must be a finite number"),
        ("max_abs_midpoint_clock_skew_seconds", -0.001, "cannot be negative"),
    ],
)
def test_fetch_okx_top_of_book_rejects_unbounded_server_timing_before_io(
    field: str,
    value: float,
    message: str,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError(
            "invalid timing policy must fail before public network or clock access"
        )

    with pytest.raises(ValueError, match=message):
        fetch_okx_top_of_book(
            instrument_id="BTC-USDT",
            instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
            get_bytes=forbidden,
            get_server_time_bytes=forbidden,
            now=forbidden,
            **{field: value},
        )
