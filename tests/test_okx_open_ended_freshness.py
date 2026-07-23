from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import gpt_quant.okx as okx
from gpt_quant import fetch_okx_history_candles

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"


def _real_okx_rows() -> list[list[str]]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["fixture_rows_sha256"] == _EXPECTED_FIXTURE_SHA256
    assert hashlib.sha256(rows_bytes).hexdigest() == _EXPECTED_FIXTURE_SHA256
    return json.loads(rows_bytes)


def _getter(rows: list[list[str]]):
    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert "instId=BTC-USDT" in url
        assert "bar=1Dutc" in url
        assert timeout == 20.0
        return {"code": "0", "msg": "", "data": [list(row) for row in rows]}

    return fake_getter


def _download(*, as_of: str | None):
    rows = _real_okx_rows()
    return fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        base_url="https://example.test",
        limit=100,
        max_pages=1,
        pause_seconds=0.0,
        as_of=as_of,
        get_json=_getter(rows),
    )


def test_open_ended_download_accepts_latest_completed_bar_before_current_bar() -> None:
    snapshot = _download(as_of="2026-07-21T12:00:00+00:00")

    assert snapshot.metadata["end"] == "2026-07-20T00:00:00+00:00"
    assert snapshot.metadata["freshness_checked_at_utc"] == "2026-07-21T12:00:00+00:00"
    assert snapshot.metadata["freshness_age_seconds"] == 36 * 60 * 60
    assert snapshot.metadata["freshness_max_age_seconds"] == 48 * 60 * 60 + 5 * 60


def test_open_ended_download_rejects_latest_completed_bar_at_stale_threshold() -> None:
    with pytest.raises(ValueError, match="open-ended download is stale"):
        _download(as_of="2026-07-22T00:05:00+00:00")


def test_open_ended_download_rejects_completed_bar_after_freshness_reference() -> None:
    with pytest.raises(ValueError, match="after the freshness reference"):
        _download(as_of="2026-07-19T12:00:00+00:00")


def test_injected_getter_without_as_of_preserves_deterministic_fixture_compatibility() -> None:
    snapshot = _download(as_of=None)

    assert snapshot.metadata["freshness_checked_at_utc"] is None
    assert snapshot.metadata["freshness_age_seconds"] is None
    assert snapshot.metadata["freshness_max_age_seconds"] is None


def test_as_of_with_default_transport_fails_before_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_calls = 0

    def unexpected_network_call(url: str, timeout: float) -> dict[str, object]:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError(f"unexpected network call to {url} with timeout {timeout}")

    monkeypatch.setattr(okx, "_default_json_getter", unexpected_network_call)

    with pytest.raises(ValueError, match="as_of is only valid with an injected get_json"):
        okx.fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            as_of="2026-07-21T12:00:00+00:00",
        )

    assert network_calls == 0


def test_default_transport_checks_freshness_after_download(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _real_okx_rows()
    download_completed = False
    clock_calls = 0

    def fake_clock() -> pd.Timestamp:
        nonlocal clock_calls
        clock_calls += 1
        reference = (
            "2026-07-22T00:05:00+00:00" if download_completed else "2026-07-22T00:04:59+00:00"
        )
        return pd.Timestamp(reference)

    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        nonlocal download_completed
        assert clock_calls == 0
        assert "instId=BTC-USDT" in url
        assert "bar=1Dutc" in url
        assert timeout == 20.0
        download_completed = True
        return {"code": "0", "msg": "", "data": [list(row) for row in rows]}

    monkeypatch.setattr(okx, "_current_utc_timestamp", fake_clock)
    monkeypatch.setattr(okx, "_default_json_getter", fake_getter)

    with pytest.raises(ValueError, match="open-ended download is stale"):
        fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            base_url="https://example.test",
            limit=100,
            max_pages=1,
            pause_seconds=0.0,
        )

    assert download_completed
    assert clock_calls == 1
