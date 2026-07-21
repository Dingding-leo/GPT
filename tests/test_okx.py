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


def _row(timestamp_ms: int, close: float, *, confirm: str = "1") -> list[str]:
    return [
        str(timestamp_ms),
        str(close - 1.0),
        str(close + 2.0),
        str(close - 2.0),
        str(close),
        "10",
        "1000",
        "1000",
        confirm,
    ]


def test_okx_pagination_drops_partial_candle_and_hashes_snapshot(tmp_path: Path) -> None:
    day = 86_400_000
    pages = {
        None: [_row(4 * day, 104.0, confirm="0"), _row(3 * day, 103.0)],
        str(3 * day): [_row(2 * day, 102.0), _row(day, 101.0)],
        str(day): [],
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

    assert list(snapshot.candles["close"]) == [101.0, 102.0, 103.0]
    assert snapshot.metadata["incomplete_rows_removed"] == 1
    assert snapshot.metadata["missing_intervals"] == 0
    assert snapshot.candles.index.is_monotonic_increasing

    paths = write_okx_snapshot(snapshot, tmp_path)
    assert (
        hashlib.sha256(paths["candles"].read_bytes()).hexdigest()
        == snapshot.metadata["normalized_csv_sha256"]
    )
    metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
    assert metadata["instrument_id"] == "BTC-USDT"
    assert paths["raw"].exists()


def test_okx_parser_rejects_invalid_ohlc() -> None:
    bad = [["1000", "100", "99", "98", "101", "1", "1", "1", "1"]]
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
