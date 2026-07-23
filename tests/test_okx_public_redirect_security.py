from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError

import pytest

from gpt_quant.okx_execution_quote import (
    _default_json_getter,
    _default_raw_bytes_getter,
)

_FIXTURE_DIR = (
    Path(__file__).parent / "fixtures" / "okx" / "order-book-btc-usdt-docs-20210826"
)
_RESPONSE_PATH = _FIXTURE_DIR / "response.json"
_EXPECTED_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_SERVER_TIME_RESPONSE = b'{"code":"0","msg":"","data":[{"ts":"1629966436500"}]}'


def _fixture_response() -> bytes:
    response = _RESPONSE_PATH.read_bytes()
    assert hashlib.sha256(response).hexdigest() == _EXPECTED_RESPONSE_SHA256
    return response


def _payload_handler(
    payload: bytes,
    contacts: list[str],
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            contacts.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    return Handler


def _redirect_handler(
    location: str,
    contacts: list[str],
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            contacts.append(self.path)
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    return Handler


@contextmanager
def _serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def _assert_cross_origin_redirect_rejected(
    getter: Callable[[str, float], object],
    *,
    destination_payload: bytes,
) -> None:
    origin_contacts: list[str] = []
    destination_contacts: list[str] = []
    with (
        _serve(_payload_handler(destination_payload, destination_contacts)) as destination,
        _serve(
            _redirect_handler(f"{destination}/link-local-target", origin_contacts)
        ) as origin,
        pytest.raises((HTTPError, RuntimeError)),
    ):
        getter(f"{origin}/public-okx-endpoint", 2.0)

    assert origin_contacts == ["/public-okx-endpoint"]
    assert destination_contacts == []


def test_default_books_transport_rejects_cross_origin_redirect() -> None:
    _assert_cross_origin_redirect_rejected(
        _default_raw_bytes_getter,
        destination_payload=_fixture_response(),
    )


def test_default_server_time_transport_rejects_cross_origin_redirect() -> None:
    _assert_cross_origin_redirect_rejected(
        _default_json_getter,
        destination_payload=_SERVER_TIME_RESPONSE,
    )
