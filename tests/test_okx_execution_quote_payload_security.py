from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant.okx_execution_quote import fetch_okx_top_of_book
from gpt_quant.okx_execution_quote_replay import ReconstructableOKXTopOfBookEvidence

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "order-book-btc-usdt-docs-20210826"
_RESPONSE_PATH = _FIXTURE_DIR / "response.json"
_EXPECTED_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_INSTRUMENT_SNAPSHOT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_MAX_BOOK_DECIMAL_CHARACTERS = 128


def _fixture_response() -> bytes:
    response = _RESPONSE_PATH.read_bytes()
    assert hashlib.sha256(response).hexdigest() == _EXPECTED_RESPONSE_SHA256
    return response


def _clock(*values: str):
    timestamps: Iterator[datetime] = iter(
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        for value in values
    )
    return lambda: next(timestamps)


def _server_time_response() -> bytes:
    return b'{"code":"0","msg":"","data":[{"ts":"1629966436500"}]}'


def _fetch(response: bytes):
    return fetch_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
        base_url="https://test.okx.com",
        get_bytes=lambda _url, _timeout: response,
        get_server_time_bytes=lambda _url, _timeout: _server_time_response(),
        now=_clock(
            "2021-08-26T08:27:16.420000Z",
            "2021-08-26T08:27:16.450000Z",
            "2021-08-26T08:27:16.460000Z",
            "2021-08-26T08:27:16.540000Z",
        ),
    )


def _mutated_response(*, field_index: int, value: str) -> bytes:
    payload = json.loads(_fixture_response())
    payload["data"][0]["asks"][0][field_index] = value
    return json.dumps(payload, separators=(",", ":")).encode()


@pytest.mark.parametrize(
    ("field_index", "field_name"),
    [
        (0, "ask_price"),
        (1, "ask_quantity"),
    ],
)
def test_fetch_okx_top_of_book_rejects_oversized_decimal_fields(
    field_index: int,
    field_name: str,
) -> None:
    response = _mutated_response(
        field_index=field_index,
        value="1" * (_MAX_BOOK_DECIMAL_CHARACTERS + 1),
    )

    with pytest.raises(
        ValueError,
        match=(
            rf"{field_name} exceeds the "
            rf"{_MAX_BOOK_DECIMAL_CHARACTERS}-character safety limit"
        ),
    ):
        _fetch(response)


@pytest.mark.parametrize("malformed", ["NaN", "1e3", "+1", " 1", ".1", "1.", "١"])
def test_fetch_okx_top_of_book_rejects_non_plain_decimal_fields(malformed: str) -> None:
    response = _mutated_response(field_index=0, value=malformed)

    with pytest.raises(ValueError, match="ask_price must be a positive ASCII decimal string"):
        _fetch(response)


def test_fetch_okx_top_of_book_canonicalizes_zero_padded_decimal_fields() -> None:
    payload = json.loads(_fixture_response())
    payload["data"][0]["asks"][0][0] = "41006.8000"
    payload["data"][0]["asks"][0][1] = "0.6003892100"
    payload["data"][0]["bids"][0][0] = "41006.3000"
    payload["data"][0]["bids"][0][1] = "0.3017821800"
    response = json.dumps(payload, separators=(",", ":")).encode()

    observation = _fetch(response)

    assert observation.source_response_sha256 == hashlib.sha256(response).hexdigest()
    assert observation.quote.ask_price == "41006.8"
    assert observation.quote.ask_quantity == "0.60038921"
    assert observation.quote.bid_price == "41006.3"
    assert observation.quote.bid_quantity == "0.30178218"
    replayed = ReconstructableOKXTopOfBookEvidence.from_json_bytes(
        ReconstructableOKXTopOfBookEvidence(observation=observation).to_json_bytes()
    )
    assert replayed.observation == observation
