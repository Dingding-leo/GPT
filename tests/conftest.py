from __future__ import annotations

import base64
import hashlib
import json
import zlib
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import validate_prices

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx"
_DATA_PATH = _FIXTURE_ROOT / "btc-usdt-1dutc-20180111-20190902.json.zlib.b64"
_METADATA_PATH = _FIXTURE_ROOT / "btc-usdt-1dutc-20180111-20190902.metadata.json"


def _load_btc_usdt_prices() -> pd.Series:
    encoded = _DATA_PATH.read_text(encoding="ascii").strip()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    actual_hash = hashlib.sha256(encoded.encode("ascii")).hexdigest()
    if actual_hash != metadata["fixture_sha256"]:
        raise RuntimeError("OKX regression fixture hash does not match its provenance metadata")
    if (
        metadata["provider"] != "OKX"
        or metadata["instrument_id"] != "BTC-USDT"
        or metadata["bar"] != "1Dutc"
        or metadata["missing_intervals"] != 0
    ):
        raise RuntimeError("OKX regression fixture metadata is incomplete or inconsistent")

    payload = json.loads(zlib.decompress(base64.b64decode(encoded)).decode("utf-8"))
    closes = payload.get("close")
    observations = int(metadata["observations"])
    if not isinstance(closes, list) or len(closes) != observations:
        raise RuntimeError("OKX regression fixture observation count is invalid")

    index = pd.date_range(
        start=pd.Timestamp(metadata["start"]),
        periods=observations,
        freq=pd.Timedelta(seconds=int(metadata["expected_step_seconds"])),
    )
    if index[-1] != pd.Timestamp(metadata["end"]):
        raise RuntimeError("OKX regression fixture timestamps do not match the metadata boundary")
    return validate_prices(pd.Series(closes, index=index, name="close"), minimum_rows=observations)


@pytest.fixture(scope="session")
def btc_usdt_prices() -> pd.Series:
    """Return a hash-verified immutable extract of completed public OKX daily closes."""

    return _load_btc_usdt_prices()
