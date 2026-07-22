from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

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


def _timestamp(row: list[str]) -> datetime:
    return datetime.fromtimestamp(int(row[0]) / 1_000, UTC)


def _getter(rows: list[list[str]]):
    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert "instId=BTC-USDT" in url
        assert timeout == 20.0
        return {"code": "0", "msg": "", "data": rows}

    return fake_getter


def test_downloader_accepts_explicit_end_covered_by_latest_completed_candle() -> None:
    _partial, day_20, day_19, _day_18, _day_17 = _real_okx_rows()

    snapshot = fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        end=_timestamp(day_20),
        base_url="https://example.test",
        limit=2,
        max_pages=1,
        pause_seconds=0.0,
        get_json=_getter([day_20, day_19]),
    )

    assert snapshot.candles.index[-1].to_pydatetime() == _timestamp(day_20)
    assert snapshot.metadata["requested_end"] == _timestamp(day_20).isoformat()


def test_downloader_accepts_end_inside_latest_completed_bar_interval() -> None:
    _partial, day_20, day_19, _day_18, _day_17 = _real_okx_rows()
    requested_end = _timestamp(day_20) + timedelta(hours=12)

    snapshot = fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        end=requested_end,
        base_url="https://example.test",
        limit=2,
        max_pages=1,
        pause_seconds=0.0,
        get_json=_getter([day_20, day_19]),
    )

    assert snapshot.candles.index[-1].to_pydatetime() == _timestamp(day_20)


def test_downloader_rejects_explicit_end_missing_boundary_candle() -> None:
    _partial, day_20, day_19, day_18, _day_17 = _real_okx_rows()

    with pytest.raises(ValueError, match="does not cover the requested end"):
        fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            end=_timestamp(day_20),
            base_url="https://example.test",
            limit=2,
            max_pages=1,
            pause_seconds=0.0,
            get_json=_getter([day_19, day_18]),
        )
