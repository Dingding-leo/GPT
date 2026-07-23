from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import (
    OKXServerTimeSample,
    build_okx_completed_bar_cutoff,
    fetch_okx_history_candles,
    sample_okx_server_time,
)

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


def _download(rows: list[list[str]], *, as_of: str):
    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert "instId=BTC-USDT" in url
        assert "bar=1Dutc" in url
        assert timeout == 20.0
        return {"code": "0", "msg": "", "data": [list(row) for row in rows]}

    return fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        base_url="https://example.test",
        limit=100,
        max_pages=1,
        pause_seconds=0.0,
        as_of=as_of,
        get_json=fake_getter,
    )


def _clock(*values: str):
    timestamps: Iterator[pd.Timestamp] = iter(pd.Timestamp(value) for value in values)
    return lambda: next(timestamps)


def _server_time_sample(
    *,
    server_time: str = "2026-07-21T12:00:00.100+00:00",
    local_started: str = "2026-07-21T12:00:00.000+00:00",
    local_received: str = "2026-07-21T12:00:00.200+00:00",
    max_round_trip_seconds: float = 2.0,
    max_abs_clock_skew_seconds: float = 5.0,
):
    server_timestamp_ms = str(int(pd.Timestamp(server_time).timestamp() * 1_000))

    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert url == "https://example.test/api/v5/public/time"
        assert timeout == 20.0
        return {"code": "0", "msg": "", "data": [{"ts": server_timestamp_ms}]}

    return sample_okx_server_time(
        base_url="https://example.test",
        timeout=20.0,
        max_round_trip_seconds=max_round_trip_seconds,
        max_abs_clock_skew_seconds=max_abs_clock_skew_seconds,
        get_json=fake_getter,
        now=_clock(local_started, local_received),
    )


def test_completed_bar_cutoff_uses_bounded_exchange_time() -> None:
    snapshot = _download(_real_okx_rows(), as_of="2026-07-21T11:59:59+00:00")
    sample = _server_time_sample()

    cutoff = build_okx_completed_bar_cutoff(snapshot, server_time_sample=sample)

    assert cutoff.instrument_id == "BTC-USDT"
    assert cutoff.bar == "1Dutc"
    assert cutoff.bar_open_utc == pd.Timestamp("2026-07-20T00:00:00+00:00")
    assert cutoff.bar_close_utc == pd.Timestamp("2026-07-21T00:00:00+00:00")
    assert cutoff.observed_at_utc == pd.Timestamp("2026-07-21T11:59:59+00:00")
    assert cutoff.exchange_observed_at_utc == pd.Timestamp("2026-07-21T12:00:00.100+00:00")
    assert cutoff.server_time_response_received_utc == pd.Timestamp("2026-07-21T12:00:00.200+00:00")
    assert cutoff.signal_not_before_utc == cutoff.server_time_response_received_utc
    assert cutoff.availability_delay_seconds == pytest.approx(12 * 60 * 60 + 0.1)
    assert cutoff.server_round_trip_seconds == pytest.approx(0.2)
    assert cutoff.midpoint_clock_skew_seconds == pytest.approx(0.0)
    assert cutoff.max_server_round_trip_seconds == pytest.approx(2.0)
    assert cutoff.max_abs_midpoint_clock_skew_seconds == pytest.approx(5.0)


def test_completed_bar_cutoff_rejects_impossible_early_confirmation() -> None:
    rows = _real_okx_rows()
    assert pd.to_datetime(int(rows[0][0]), unit="ms", utc=True) == pd.Timestamp(
        "2026-07-21T00:00:00+00:00"
    )
    rows[0][-1] = "1"
    snapshot = _download(rows, as_of="2026-07-21T12:00:00+00:00")
    sample = _server_time_sample(
        server_time="2026-07-21T12:00:01.100+00:00",
        local_started="2026-07-21T12:00:01.000+00:00",
        local_received="2026-07-21T12:00:01.200+00:00",
    )

    with pytest.raises(
        ValueError,
        match="latest confirmed OKX candle has not closed according to server time",
    ):
        build_okx_completed_bar_cutoff(snapshot, server_time_sample=sample)


def test_completed_bar_cutoff_rejects_forged_server_time_sample() -> None:
    rows = _real_okx_rows()
    rows[0][-1] = "1"
    snapshot = _download(rows, as_of="2026-07-21T12:00:00+00:00")
    forged_sample = OKXServerTimeSample(
        base_url="https://example.test",
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp("2026-07-21T12:00:01.000+00:00"),
        local_response_received_utc=pd.Timestamp("2026-07-21T12:00:01.200+00:00"),
        server_time_utc=pd.Timestamp("2026-07-22T00:00:01.000+00:00"),
        round_trip_seconds=0.2,
        midpoint_clock_skew_seconds=0.0,
    )

    with pytest.raises(ValueError, match="clock skew does not match its timestamps"):
        build_okx_completed_bar_cutoff(
            snapshot,
            server_time_sample=forged_sample,
        )


def test_completed_bar_cutoff_applies_its_own_network_bound() -> None:
    snapshot = _download(_real_okx_rows(), as_of="2026-07-21T11:59:59+00:00")
    loosely_sampled = _server_time_sample(
        server_time="2026-07-21T12:00:00.750+00:00",
        local_started="2026-07-21T12:00:00.000+00:00",
        local_received="2026-07-21T12:00:01.500+00:00",
        max_round_trip_seconds=2.0,
    )

    with pytest.raises(ValueError, match="round trip exceeds the live cutoff bound"):
        build_okx_completed_bar_cutoff(
            snapshot,
            server_time_sample=loosely_sampled,
            max_round_trip_seconds=1.0,
        )


def test_completed_bar_cutoff_rejects_post_download_metadata_mutation() -> None:
    snapshot = _download(_real_okx_rows(), as_of="2026-07-21T11:59:59+00:00")
    snapshot.metadata["freshness_age_seconds"] = 0.0

    with pytest.raises(ValueError, match="snapshot metadata changed after download"):
        build_okx_completed_bar_cutoff(
            snapshot,
            server_time_sample=_server_time_sample(),
        )


def test_completed_bar_cutoff_requires_server_sample_after_candle_download() -> None:
    snapshot = _download(_real_okx_rows(), as_of="2026-07-21T12:00:01+00:00")
    stale_sample = _server_time_sample()

    with pytest.raises(ValueError, match="sampled after the candle download"):
        build_okx_completed_bar_cutoff(snapshot, server_time_sample=stale_sample)


def test_server_time_sample_rejects_excessive_clock_skew() -> None:
    with pytest.raises(ValueError, match="clock skew"):
        _server_time_sample(
            server_time="2026-07-21T12:00:10.000+00:00",
            max_abs_clock_skew_seconds=1.0,
        )


def test_server_time_sample_rejects_excessive_round_trip() -> None:
    with pytest.raises(ValueError, match="round trip"):
        _server_time_sample(
            local_received="2026-07-21T12:00:03.000+00:00",
            max_round_trip_seconds=2.0,
        )
