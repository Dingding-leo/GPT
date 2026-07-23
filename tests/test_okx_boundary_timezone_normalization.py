from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

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


def _download(*, start: str, end: str):
    rows = _real_okx_rows()
    return fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        start=start,
        end=end,
        base_url="https://example.test",
        limit=100,
        max_pages=1,
        pause_seconds=0.0,
        get_json=_getter(rows),
    )


def test_timezone_equivalent_boundaries_select_identical_real_okx_bars() -> None:
    utc = _download(
        start="2026-07-18T00:00:00+00:00",
        end="2026-07-20T00:00:00+00:00",
    )
    adelaide_offset = _download(
        start="2026-07-18T09:30:00+09:30",
        end="2026-07-20T09:30:00+09:30",
    )
    naive_utc = _download(
        start="2026-07-18 00:00:00",
        end="2026-07-20 00:00:00",
    )
    date_only = _download(
        start="2026-07-18",
        end="2026-07-20",
    )

    pd.testing.assert_frame_equal(
        adelaide_offset.candles,
        utc.candles,
        check_exact=True,
    )
    pd.testing.assert_frame_equal(naive_utc.candles, utc.candles, check_exact=True)
    pd.testing.assert_frame_equal(date_only.candles, utc.candles, check_exact=True)

    for snapshot in (utc, adelaide_offset, naive_utc, date_only):
        assert snapshot.metadata["requested_start"] == "2026-07-18T00:00:00+00:00"
        assert snapshot.metadata["requested_end"] == "2026-07-20T00:00:00+00:00"
        assert snapshot.metadata["start"] == "2026-07-18T00:00:00+00:00"
        assert snapshot.metadata["end"] == "2026-07-20T00:00:00+00:00"
        assert snapshot.metadata["observations"] == 3
        assert snapshot.metadata["normalized_csv_sha256"] == utc.metadata["normalized_csv_sha256"]
        assert snapshot.metadata["raw_pages_sha256"] == utc.metadata["raw_pages_sha256"]
