from __future__ import annotations

import base64
import gzip
import hashlib
import io
import json
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import validate_prices

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx"
_FIXTURE_DATA = _FIXTURE_DIR / "btc_usdt_1dutc_20180111_20191211.csv.gz.b64"
_FIXTURE_METADATA = _FIXTURE_DIR / "btc_usdt_1dutc_20180111_20191211.metadata.json"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture(scope="session")
def btc_usdt_prices() -> pd.Series:
    """Load immutable, hash-verified public OKX BTC-USDT daily closes."""

    metadata = json.loads(_FIXTURE_METADATA.read_text(encoding="utf-8"))
    compressed = base64.b64decode(_FIXTURE_DATA.read_text(encoding="ascii"), validate=True)
    assert _sha256(compressed) == metadata["fixture_compressed_sha256"]

    csv_bytes = gzip.decompress(compressed)
    assert _sha256(csv_bytes) == metadata["fixture_csv_sha256"]

    frame = pd.read_csv(io.BytesIO(csv_bytes))
    index = pd.to_datetime(frame["timestamp"], utc=True, errors="raise")
    prices = validate_prices(pd.Series(frame["close"].to_numpy(), index=index, name="close"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert len(prices) == metadata["observations"]
    assert prices.index[0].isoformat() == pd.Timestamp(metadata["start"]).isoformat()
    assert prices.index[-1].isoformat() == pd.Timestamp(metadata["end"]).isoformat()
    return prices
