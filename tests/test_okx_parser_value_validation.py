from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gpt_quant.okx import parse_okx_candle_rows

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"


def _real_confirmed_okx_row() -> list[str]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert hashlib.sha256(rows_bytes).hexdigest() == metadata["fixture_rows_sha256"]

    rows = json.loads(rows_bytes)
    return list(next(row for row in rows if row[8] == "1"))


@pytest.mark.parametrize(
    ("field_index", "replacement", "message"),
    [
        (4, "inf", "non-finite market-data value"),
        (4, "0", "prices must be strictly positive"),
        (5, "-1", "volumes cannot be negative"),
        (8, "2", "invalid confirm flag"),
    ],
)
def test_okx_parser_rejects_invalid_values_in_real_exchange_row(
    field_index: int,
    replacement: str,
    message: str,
) -> None:
    corrupted = _real_confirmed_okx_row()
    corrupted[field_index] = replacement

    with pytest.raises(ValueError, match=message):
        parse_okx_candle_rows([corrupted])


@pytest.mark.parametrize(
    "replacement",
    ["not-a-timestamp", "nan", None, "999999999999999999999999999999"],
)
def test_okx_parser_rejects_invalid_timestamp_in_real_exchange_row(replacement: object) -> None:
    corrupted: list[object] = _real_confirmed_okx_row()
    corrupted[0] = replacement

    with pytest.raises(ValueError, match="invalid timestamp"):
        parse_okx_candle_rows([corrupted])
