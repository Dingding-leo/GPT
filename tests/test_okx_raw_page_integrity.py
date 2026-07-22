from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from gpt_quant.okx import fetch_okx_history_candles

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"


def _real_okx_rows() -> list[list[str]]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert hashlib.sha256(rows_bytes).hexdigest() == metadata["fixture_rows_sha256"]

    rows = json.loads(rows_bytes)
    assert len(rows) == metadata["observations"]
    return [list(row) for row in rows]


def _getter_for_pages(pages: dict[str | None, list[list[str]]]):
    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert timeout == 20.0
        cursor = parse_qs(urlparse(url).query).get("after", [None])[0]
        return {"code": "0", "msg": "", "data": pages[cursor]}

    return fake_getter


def test_okx_downloader_allows_exact_pagination_overlap() -> None:
    _partial, day_20, day_19, day_18, _day_17 = _real_okx_rows()
    pages = {
        None: [day_20, day_19],
        day_19[0]: [day_19, day_18],
        day_18[0]: [],
    }

    snapshot = fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        base_url="https://example.test",
        limit=2,
        max_pages=5,
        pause_seconds=0.0,
        get_json=_getter_for_pages(pages),
    )

    assert snapshot.metadata["duplicates_removed"] == 1
    assert list(snapshot.candles["close"]) == [
        float(day_18[4]),
        float(day_19[4]),
        float(day_20[4]),
    ]


def test_okx_downloader_rejects_page_not_newest_to_oldest() -> None:
    _partial, day_20, day_19, _day_18, _day_17 = _real_okx_rows()

    with pytest.raises(ValueError, match="strictly newest-to-oldest"):
        fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            base_url="https://example.test",
            limit=2,
            max_pages=1,
            pause_seconds=0.0,
            get_json=_getter_for_pages({None: [day_19, day_20]}),
        )


def test_okx_downloader_rejects_rows_newer_than_pagination_cursor() -> None:
    _partial, day_20, day_19, day_18, _day_17 = _real_okx_rows()
    pages = {
        None: [day_20, day_19],
        day_19[0]: [day_20, day_18],
    }

    with pytest.raises(RuntimeError, match="newer than the requested cursor"):
        fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            base_url="https://example.test",
            limit=2,
            max_pages=5,
            pause_seconds=0.0,
            get_json=_getter_for_pages(pages),
        )


def test_okx_downloader_rejects_conflicting_pagination_overlap() -> None:
    _partial, day_20, day_19, day_18, _day_17 = _real_okx_rows()
    conflicting_day_19 = list(day_19)
    conflicting_day_19[7] = f"{conflicting_day_19[7]}0"
    pages = {
        None: [day_20, day_19],
        day_19[0]: [conflicting_day_19, day_18],
    }

    with pytest.raises(ValueError, match="conflicts with an earlier row for timestamp"):
        fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            base_url="https://example.test",
            limit=2,
            max_pages=5,
            pause_seconds=0.0,
            get_json=_getter_for_pages(pages),
        )


def test_okx_downloader_rejects_raw_schema_extension() -> None:
    _partial, day_20, _day_19, _day_18, _day_17 = _real_okx_rows()
    extended = [*day_20, "unexpected-field"]

    with pytest.raises(ValueError, match="must contain exactly 9 fields"):
        fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            base_url="https://example.test",
            limit=1,
            max_pages=1,
            pause_seconds=0.0,
            get_json=_getter_for_pages({None: [extended]}),
        )
