from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from gpt_quant.maker_fill_replay import OKXPublicTradeSnapshot

_FIXTURE = (
    Path(__file__).parent / "fixtures" / "okx" / "trades-btc-usdt-docs-20220602" / "response.json"
)
_EXPECTED_SHA256 = "01438cc23709d9c8e9ea8d9d49d3f64c65978d27d592356a333f7a3da213d563"


@pytest.mark.parametrize(
    ("field", "expected_error"),
    [
        ("px", "price exceeds the 128-character security limit"),
        ("sz", "base_quantity exceeds the 128-character security limit"),
    ],
)
def test_oversized_public_trade_decimal_fails_closed(
    field: str,
    expected_error: str,
) -> None:
    source = _FIXTURE.read_bytes()
    assert hashlib.sha256(source).hexdigest() == _EXPECTED_SHA256

    payload = json.loads(source)
    payload["data"][0][field] = "1" * 129
    corrupted = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    with pytest.raises(ValueError, match=expected_error):
        OKXPublicTradeSnapshot.from_json_bytes(corrupted)
