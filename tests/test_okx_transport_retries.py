from __future__ import annotations

import hashlib
import json
from email.utils import formatdate
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

import gpt_quant.okx as okx

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_RETRYABLE_HTTP_STATUS_CODES = (408, 429, 500, 502, 503, 504)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    @classmethod
    def from_payload(cls, payload: dict[str, object]) -> _Response:
        return cls(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _real_okx_payload() -> dict[str, object]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["fixture_rows_sha256"] == _EXPECTED_FIXTURE_SHA256
    assert hashlib.sha256(rows_bytes).hexdigest() == _EXPECTED_FIXTURE_SHA256
    rows = json.loads(rows_bytes)
    assert isinstance(rows, list)
    return {"code": "0", "msg": "", "data": rows}


def _download_with_default_transport() -> okx.OKXCandleSnapshot:
    return okx.fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        base_url="https://www.okx.com",
        limit=5,
        max_pages=1,
        pause_seconds=0.0,
    )


def _assert_request_contract(request: Any, timeout: float) -> None:
    assert timeout == 20.0
    assert "/api/v5/market/history-candles?" in request.full_url
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("User-agent") == (
        "gpt-quant-lab/0.2 (+https://github.com/Dingding-leo/GPT)"
    )


@pytest.mark.parametrize("status_code", _RETRYABLE_HTTP_STATUS_CODES)
def test_public_downloader_retries_every_declared_transient_http_status(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _real_okx_payload()
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        _assert_request_contract(request, timeout)
        if attempts < 3:
            raise HTTPError(
                request.full_url,
                status_code,
                f"transient HTTP {status_code}",
                hdrs=None,
                fp=None,
            )
        return _Response.from_payload(payload)

    monkeypatch.setattr(okx, "urlopen", fake_urlopen)
    monkeypatch.setattr(okx.time, "sleep", sleeps.append)

    snapshot = _download_with_default_transport()

    assert attempts == 3
    assert sleeps == [0.5, 1.0]
    assert snapshot.metadata["provider"] == "OKX"
    assert snapshot.metadata["instrument_id"] == "BTC-USDT"
    assert snapshot.metadata["bar"] == "1Dutc"
    assert snapshot.metadata["raw_rows"] == 5


@pytest.mark.parametrize("status_code", [400, 401, 403, 404, 422])
def test_public_downloader_does_not_retry_permanent_http_statuses(
    status_code: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        _assert_request_contract(request, timeout)
        raise HTTPError(
            request.full_url,
            status_code,
            f"permanent HTTP {status_code}",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(okx, "urlopen", fake_urlopen)
    monkeypatch.setattr(okx.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match=rf"OKX HTTP error {status_code}"):
        _download_with_default_transport()

    assert attempts == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(URLError("temporary name-resolution failure"), id="url-error"),
        pytest.param(TimeoutError("temporary socket timeout"), id="timeout"),
    ],
)
def test_public_downloader_bounds_transport_failure_retries(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        _assert_request_contract(request, timeout)
        raise failure

    monkeypatch.setattr(okx, "urlopen", fake_urlopen)
    monkeypatch.setattr(okx.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match="OKX request failed after retries"):
        _download_with_default_transport()

    assert attempts == 3
    assert sleeps == [0.5, 1.0]


def test_public_downloader_recovers_from_transient_malformed_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _real_okx_payload()
    responses = [_Response(b"{"), _Response.from_payload(payload)]
    sleeps: list[float] = []
    attempts = 0

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        _assert_request_contract(request, timeout)
        return responses.pop(0)

    monkeypatch.setattr(okx, "urlopen", fake_urlopen)
    monkeypatch.setattr(okx.time, "sleep", sleeps.append)

    snapshot = _download_with_default_transport()

    assert attempts == 2
    assert sleeps == [0.5]
    assert snapshot.metadata["raw_rows"] == 5


def test_public_downloader_bounds_malformed_json_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        _assert_request_contract(request, timeout)
        return _Response(b"{")

    monkeypatch.setattr(okx, "urlopen", fake_urlopen)
    monkeypatch.setattr(okx.time, "sleep", sleeps.append)

    with pytest.raises(RuntimeError, match="OKX request failed after retries"):
        _download_with_default_transport()

    assert attempts == 3
    assert sleeps == [0.5, 1.0]


def test_public_downloader_honors_and_caps_retry_after_delta_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _real_okx_payload()
    retry_after_values = ["3", "999"]
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        _assert_request_contract(request, timeout)
        if attempts <= len(retry_after_values):
            raise HTTPError(
                request.full_url,
                429,
                "rate limited",
                hdrs={"Retry-After": retry_after_values[attempts - 1]},
                fp=None,
            )
        return _Response.from_payload(payload)

    monkeypatch.setattr(okx, "urlopen", fake_urlopen)
    monkeypatch.setattr(okx.time, "sleep", sleeps.append)

    snapshot = _download_with_default_transport()

    assert attempts == 3
    assert sleeps == [3.0, 5.0]
    assert snapshot.metadata["raw_rows"] == 5


def test_public_downloader_caps_oversized_retry_after_without_integer_parsing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _real_okx_payload()
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        _assert_request_contract(request, timeout)
        if attempts == 1:
            raise HTTPError(
                request.full_url,
                429,
                "rate limited",
                hdrs={"Retry-After": "9" * 10_000},
                fp=None,
            )
        return _Response.from_payload(payload)

    monkeypatch.setattr(okx, "urlopen", fake_urlopen)
    monkeypatch.setattr(okx.time, "sleep", sleeps.append)

    snapshot = _download_with_default_transport()

    assert attempts == 2
    assert sleeps == [5.0]
    assert snapshot.metadata["raw_rows"] == 5


def test_public_downloader_honors_retry_after_http_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _real_okx_payload()
    now = 1_800_000_000.0
    retry_after = formatdate(now + 4.0, usegmt=True)
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        _assert_request_contract(request, timeout)
        if attempts == 1:
            raise HTTPError(
                request.full_url,
                503,
                "temporarily unavailable",
                hdrs={"Retry-After": retry_after},
                fp=None,
            )
        return _Response.from_payload(payload)

    monkeypatch.setattr(okx, "urlopen", fake_urlopen)
    monkeypatch.setattr(okx.time, "time", lambda: now)
    monkeypatch.setattr(okx.time, "sleep", sleeps.append)

    snapshot = _download_with_default_transport()

    assert attempts == 2
    assert sleeps == [4.0]
    assert snapshot.metadata["raw_rows"] == 5


@pytest.mark.parametrize("retry_after", ["", "invalid", "-1", "0", "0.1"])
def test_public_downloader_falls_back_for_invalid_or_short_retry_after(
    retry_after: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _real_okx_payload()
    attempts = 0
    sleeps: list[float] = []

    def fake_urlopen(request: Any, timeout: float) -> _Response:
        nonlocal attempts
        attempts += 1
        _assert_request_contract(request, timeout)
        if attempts == 1:
            raise HTTPError(
                request.full_url,
                429,
                "rate limited",
                hdrs={"Retry-After": retry_after},
                fp=None,
            )
        return _Response.from_payload(payload)

    monkeypatch.setattr(okx, "urlopen", fake_urlopen)
    monkeypatch.setattr(okx.time, "sleep", sleeps.append)

    snapshot = _download_with_default_transport()

    assert attempts == 2
    assert sleeps == [0.5]
    assert snapshot.metadata["raw_rows"] == 5
