from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from gpt_quant import (
    fetch_okx_history_candles,
    parse_okx_candle_rows,
    write_okx_snapshot,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_ROW_SCHEMA = [
    "ts",
    "open",
    "high",
    "low",
    "close",
    "volume_base",
    "volume_quote",
    "volume_quote_alt",
    "confirm",
]
_EXPECTED_SOURCE_RAW_MEMBER = "okx/BTC-USDT/snapshot/okx-BTC-USDT-1Dutc.raw.json"
_MILLISECONDS_PER_DAY = 86_400_000


def _canonical_json_sha256(value: object) -> str:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _real_okx_rows() -> list[list[str]]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["row_schema"] == _EXPECTED_ROW_SCHEMA
    assert metadata["source_raw_pages_member"] == _EXPECTED_SOURCE_RAW_MEMBER
    assert metadata["source_page_index"] == 0
    assert metadata["source_row_start"] == 0
    assert metadata["source_row_end_exclusive"] == metadata["observations"]
    assert hashlib.sha256(rows_bytes).hexdigest() == metadata["fixture_rows_sha256"]

    rows = json.loads(rows_bytes)
    assert _canonical_json_sha256(rows) == metadata["source_slice_canonical_sha256"]
    assert len(rows) == metadata["observations"]
    assert all(isinstance(row, list) and len(row) == len(_EXPECTED_ROW_SCHEMA) for row in rows)
    assert all(isinstance(value, str) for row in rows for value in row)
    assert sum(row[8] == "1" for row in rows) == metadata["confirmed_rows"]
    assert sum(row[8] == "0" for row in rows) == metadata["unconfirmed_rows"]
    return [list(row) for row in rows]


def _timestamp_iso(row: list[str]) -> str:
    return datetime.fromtimestamp(int(row[0]) / 1_000, UTC).isoformat()


def test_real_okx_raw_fixture_matches_declared_chronology() -> None:
    rows = _real_okx_rows()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    timestamps = [int(row[0]) for row in rows]

    assert len(timestamps) == len(set(timestamps))
    assert all(newer > older for newer, older in pairwise(timestamps))
    assert all(newer - older == _MILLISECONDS_PER_DAY for newer, older in pairwise(timestamps))
    assert _timestamp_iso(rows[0]) == metadata["end"]
    assert _timestamp_iso(rows[-1]) == metadata["start"]


def test_okx_pagination_drops_partial_candle_and_hashes_snapshot(
    tmp_path: Path,
) -> None:
    partial, day_20, day_19, day_18, _day_17 = _real_okx_rows()
    pages = {
        None: [partial, day_20],
        day_20[0]: [day_19, day_18],
        day_18[0]: [],
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

    assert list(snapshot.candles["close"]) == [
        float(day_18[4]),
        float(day_19[4]),
        float(day_20[4]),
    ]
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
    _partial, day_20, day_19, day_18, _day_17 = _real_okx_rows()

    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        return {
            "code": "0",
            "msg": "",
            "data": [day_20, day_19],
        }

    with pytest.raises(RuntimeError, match="max_pages.*requested start"):
        fetch_okx_history_candles(
            start=_timestamp_iso(day_18),
            limit=2,
            max_pages=1,
            pause_seconds=0.0,
            get_json=fake_getter,
        )


def test_okx_marks_latest_window_when_max_pages_is_intentional() -> None:
    _partial, day_20, day_19, _day_18, _day_17 = _real_okx_rows()

    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        return {
            "code": "0",
            "msg": "",
            "data": [day_20, day_19],
        }

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


def test_okx_parser_rejects_invalid_ohlc() -> None:
    bad = _real_okx_rows()[1]
    bad[2] = bad[3]

    with pytest.raises(ValueError, match="high"):
        parse_okx_candle_rows([bad])


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
