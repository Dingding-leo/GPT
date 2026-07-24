from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from gpt_quant.okx_execution_quote import fetch_okx_top_of_book

_EXPECTED_BOOK_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_INSTRUMENT_SNAPSHOT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_BOOK_RESPONSE = (
    b'{"code":"0","data":[{"asks":[["41006.8","0.60038921","0","1"]],'
    b'"bids":[["41006.3","0.30178218","0","2"]],"seqId":3235851742,'
    b'"ts":"1629966436396"}],"msg":""}\n'
)
_SERVER_TIME_RESPONSE = b'{"code":"0","msg":"","data":[{"ts":"1629966436500"}]}'
_MAX_API_CODE_CHARACTERS = 32
_MAX_API_MESSAGE_UTF8_BYTES = 512


def _clock(*values: str):
    timestamps: Iterator[datetime] = iter(
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        for value in values
    )
    return lambda: next(timestamps)


def _fetch(
    *,
    books_response: bytes = _BOOK_RESPONSE,
    server_time_response: bytes = _SERVER_TIME_RESPONSE,
):
    assert hashlib.sha256(_BOOK_RESPONSE).hexdigest() == _EXPECTED_BOOK_RESPONSE_SHA256
    return fetch_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
        base_url="https://test.okx.com",
        get_bytes=lambda _url, _timeout: books_response,
        get_server_time_bytes=lambda _url, _timeout: server_time_response,
        now=_clock(
            "2021-08-26T08:27:16.420000Z",
            "2021-08-26T08:27:16.450000Z",
            "2021-08-26T08:27:16.460000Z",
            "2021-08-26T08:27:16.540000Z",
        ),
    )


def _mutate(response: bytes, **changes: object) -> bytes:
    payload = json.loads(response)
    payload.update(changes)
    return json.dumps(payload, separators=(",", ":")).encode()


def test_books_response_rejects_oversized_success_message_before_snapshotting() -> None:
    response = _mutate(_BOOK_RESPONSE, msg="X" * (_MAX_API_MESSAGE_UTF8_BYTES + 1))

    with pytest.raises(
        ValueError,
        match=rf"books response message exceeds the {_MAX_API_MESSAGE_UTF8_BYTES}-byte safety limit",
    ):
        _fetch(books_response=response)


def test_books_response_rejects_oversized_error_message_before_log_amplification() -> None:
    response = _mutate(
        _BOOK_RESPONSE,
        code="50011",
        msg="Y" * (_MAX_API_MESSAGE_UTF8_BYTES + 1),
        data=[],
    )

    with pytest.raises(
        ValueError,
        match=rf"books response message exceeds the {_MAX_API_MESSAGE_UTF8_BYTES}-byte safety limit",
    ):
        _fetch(books_response=response)


def test_server_time_response_rejects_oversized_message_before_clock_validation() -> None:
    response = _mutate(
        _SERVER_TIME_RESPONSE,
        msg="Z" * (_MAX_API_MESSAGE_UTF8_BYTES + 1),
    )

    with pytest.raises(
        ValueError,
        match=(
            rf"server-time response message exceeds the "
            rf"{_MAX_API_MESSAGE_UTF8_BYTES}-byte safety limit"
        ),
    ):
        _fetch(server_time_response=response)


def test_books_response_rejects_oversized_or_non_ascii_api_codes() -> None:
    for code in ("9" * (_MAX_API_CODE_CHARACTERS + 1), "１２３"):
        response = _mutate(_BOOK_RESPONSE, code=code, data=[])
        with pytest.raises(
            ValueError,
            match=rf"books response code must be 1-{_MAX_API_CODE_CHARACTERS} ASCII digits",
        ):
            _fetch(books_response=response)
