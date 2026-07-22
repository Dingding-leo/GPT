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


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_okx_parser_requires_exact_real_exchange_row_schema(mutation: str) -> None:
    corrupted = _real_confirmed_okx_row()
    if mutation == "missing":
        corrupted.pop()
    else:
        corrupted.append("unexpected-field")

    with pytest.raises(ValueError, match="must contain exactly 9 fields"):
        parse_okx_candle_rows([corrupted])
