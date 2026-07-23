from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import (
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


def _clock(*values: str):
    timestamps: Iterator[pd.Timestamp] = iter(pd.Timestamp(value) for value in values)
    return lambda: next(timestamps)


def test_completed_bar_cutoff_rejects_snapshot_missing_newly_completed_bar() -> None:
    rows = _real_okx_rows()

    def candle_getter(url: str, timeout: float) -> dict[str, object]:
        assert "instId=BTC-USDT" in url
        assert "bar=1Dutc" in url
        assert timeout == 20.0
        return {"code": "0", "msg": "", "data": [list(row) for row in rows]}

    snapshot = fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        base_url="https://example.test",
        limit=100,
        max_pages=1,
        pause_seconds=0.0,
        as_of="2026-07-21T23:59:59.900+00:00",
        get_json=candle_getter,
    )

    def time_getter(url: str, timeout: float) -> dict[str, object]:
        assert url == "https://example.test/api/v5/public/time"
        assert timeout == 20.0
        return {"code": "0", "msg": "", "data": [{"ts": "1784678400100"}]}

    sample = sample_okx_server_time(
        base_url="https://example.test",
        get_json=time_getter,
        now=_clock(
            "2026-07-22T00:00:00.000+00:00",
            "2026-07-22T00:00:00.200+00:00",
        ),
    )

    assert snapshot.candles.index[-1] == pd.Timestamp("2026-07-20T00:00:00+00:00")
    with pytest.raises(ValueError, match="stale relative to server time"):
        build_okx_completed_bar_cutoff(snapshot, server_time_sample=sample)
