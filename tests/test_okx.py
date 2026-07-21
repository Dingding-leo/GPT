from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from gpt_quant import (
    fetch_okx_history_candles,
    parse_okx_candle_rows,
    write_okx_snapshot,
)

# Exact public OKX BTC-USDT 1Dutc rows from workflow run 29841895366,
# artifact 8499721759, raw-pages SHA-256
# 59877841d17d037f8dd5e848d202d4636fbe663b3d96b8300109fc3348597334.
_REAL_ROWS = [
    [
        "1784592000000",
        "65259.5",
        "66955",
        "65153.6",
        "66743.3",
        "4893.62961396",
        "323912696.522452941",
        "323912696.522452941",
        "0",
    ],
    [
        "1784505600000",
        "64730.8",
        "65797.8",
        "63762.4",
        "65259.4",
        "6784.73202021",
        "439450219.973016317",
        "439450219.973016317",
        "1",
    ],
    [
        "1784419200000",
        "64834",
        "64967.9",
        "64270",
        "64730.7",
        "6258.51230954",
        "403958317.850158343",
        "403958317.850158343",
        "1",
    ],
    [
        "1784332800000",
        "63937.3",
        "64872.7",
        "63886.6",
        "64833.9",
        "1809.65919575",
        "116409762.485911622",
        "116409762.485911622",
        "1",
    ],
]


def test_okx_pagination_drops_partial_candle_and_hashes_snapshot(
    tmp_path: Path,
) -> None:
    pages = {
        None: _REAL_ROWS[:2],
        _REAL_ROWS[1][0]: _REAL_ROWS[2:],
        _REAL_ROWS[-1][0]: [],
    }

    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert timeout == 20.0
        query = parse_qs(urlparse(url).query)
        cursor = query.get("after", [None])[0]
        return {"code": "0", "msg": "", "data": pages[cursor]}

    snapshot = fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        base_url="https://example.test",
        limit=2,
        max_pages=5,
        pause_seconds=0.0,
        get_json=fake_getter,
    )

    assert list(snapshot.candles["close"]) == [64833.9, 64730.7, 65259.4]
    assert snapshot.metadata["incomplete_rows_removed"] == 1
    assert snapshot.metadata["missing_intervals"] == 0
    assert snapshot.metadata["pagination_termination"] == "empty_page"
    assert snapshot.metadata["pagination_complete"] is True
    assert snapshot.metadata["limit"] == 2
    assert snapshot.metadata["max_pages"] == 5
    assert snapshot.candles.index.is_monotonic_increasing

    paths = write_okx_snapshot(snapshot, tmp_path)
    assert (
        hashlib.sha256(paths["candles"].read_bytes()).hexdigest()
        == snapshot.metadata["normalized_csv_sha256"]
    )
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    assert metadata["instrument_id"] == "BTC-USDT"
    assert paths["raw"].exists()


def test_okx_rejects_max_pages_truncation_before_requested_start() -> None:
    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        return {"code": "0", "msg": "", "data": _REAL_ROWS[1:3]}

    with pytest.raises(RuntimeError, match="max_pages.*requested start"):
        fetch_okx_history_candles(
            start="1970-01-02",
            limit=2,
            max_pages=1,
            pause_seconds=0.0,
            get_json=fake_getter,
        )


def test_okx_marks_latest_window_when_max_pages_is_intentional() -> None:
    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        return {"code": "0", "msg": "", "data": _REAL_ROWS[1:3]}

    snapshot = fetch_okx_history_candles(
        limit=2,
        max_pages=1,
        pause_seconds=0.0,
        get_json=fake_getter,
    )

    assert snapshot.metadata["pagination_termination"] == "max_pages"
    assert snapshot.metadata["pagination_complete"] is False
    assert snapshot.metadata["requested_start_reached"] is False
    assert snapshot.metadata["observations"] == 2


def test_okx_parser_rejects_structurally_invalid_real_row() -> None:
    bad = [list(_REAL_ROWS[1])]
    bad[0][2] = "63000"
    with pytest.raises(ValueError, match="high"):
        parse_okx_candle_rows(bad)


def test_okx_api_error_is_not_silently_accepted() -> None:
    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        return {"code": "50011", "msg": "rate limit", "data": []}

    with pytest.raises(RuntimeError, match="50011"):
        fetch_okx_history_candles(
            limit=2,
            max_pages=1,
            pause_seconds=0.0,
            get_json=fake_getter,
        )
