from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gpt_quant.okx import fetch_okx_history_candles

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_MILLISECONDS_PER_HOUR = 3_600_000


def _real_okx_rows() -> list[list[str]]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["fixture_rows_sha256"] == _EXPECTED_FIXTURE_SHA256
    assert hashlib.sha256(rows_bytes).hexdigest() == _EXPECTED_FIXTURE_SHA256

    rows = json.loads(rows_bytes)
    assert len(rows) == metadata["observations"]
    return [list(row) for row in rows]


def test_okx_1dutc_rejects_candles_shifted_from_midnight_utc() -> None:
    shifted_rows = _real_okx_rows()
    for row in shifted_rows:
        row[0] = str(int(row[0]) + _MILLISECONDS_PER_HOUR)

    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        return {"code": "0", "msg": "", "data": shifted_rows}

    with pytest.raises(ValueError, match="midnight UTC"):
        fetch_okx_history_candles(
            inst_id="BTC-USDT",
            bar="1Dutc",
            limit=len(shifted_rows),
            max_pages=1,
            pause_seconds=0.0,
            get_json=fake_getter,
        )
