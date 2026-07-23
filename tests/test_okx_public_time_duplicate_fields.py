from __future__ import annotations

import hashlib
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator

import pytest

from gpt_quant.okx_execution_quote import _default_json_getter

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "public-time-docs-example"
_RESPONSE_PATH = _FIXTURE_DIR / "response.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_RESPONSE_SHA256 = "30565a20264d533e115834fcfd08e0009e31a28047f935c4e6b7e7cd7d35b7d6"


def _official_response() -> bytes:
    response = _RESPONSE_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["endpoint"] == "/api/v5/public/time"
    assert metadata["source_kind"] == "official_documentation_response_example"
    assert metadata["response_sha256"] == _EXPECTED_RESPONSE_SHA256
    assert hashlib.sha256(response).hexdigest() == _EXPECTED_RESPONSE_SHA256
    return response


@contextmanager
def _serve(payload: bytes) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}/api/v5/public/time"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)


def test_public_time_transport_rejects_duplicate_nested_timestamp() -> None:
    corrupted = _official_response().replace(
        b'"ts":"1597026383085"',
        b'"ts":"1597026383085","ts":"1597026383085"',
        1,
    )

    with _serve(corrupted) as url, pytest.raises(ValueError, match="duplicate field 'ts'"):
        _default_json_getter(url, 2.0)
