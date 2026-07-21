from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import validate_prices

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-20180111-20200628"
_CLOSES_PATH = _FIXTURE_DIR / "closes.json"
_TIMESTAMPS_PATH = _FIXTURE_DIR / "timestamps.zlib"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_HEX_DIGITS = frozenset("0123456789abcdef")
_REQUIRED_METADATA = {
    "provider",
    "instrument_id",
    "bar",
    "confirmed_only",
    "start",
    "end",
    "observations",
    "fixture_closes_sha256",
    "fixture_timestamps_sha256",
    "source_artifact_id",
    "source_artifact_sha256",
    "source_head_sha",
    "source_normalized_csv_sha256",
    "source_raw_pages_sha256",
    "source_workflow_run_id",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _is_sha256(value: object) -> bool:
    normalized = str(value).lower()
    return len(normalized) == 64 and set(normalized) <= _HEX_DIGITS


def _load_timestamp_milliseconds(observations: int) -> list[int]:
    actual_sha256 = hashlib.sha256(_TIMESTAMPS_PATH.read_bytes()).hexdigest()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    _require(
        metadata["fixture_timestamps_sha256"] == actual_sha256,
        "OKX timestamp fixture hash does not match its provenance metadata",
    )
    try:
        payload = zlib.decompress(_TIMESTAMPS_PATH.read_bytes())
    except zlib.error as exc:
        raise RuntimeError("OKX timestamp fixture is not valid zlib data") from exc
    _require(
        len(payload) == observations * 8,
        "OKX timestamp fixture observation count is invalid",
    )
    return [value[0] for value in struct.iter_unpack(">q", payload)]


def _load_btc_usdt_prices() -> pd.Series:
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    missing = sorted(_REQUIRED_METADATA - set(metadata))
    _require(not missing, f"OKX fixture metadata is missing required keys: {missing}")
    _require(metadata["provider"] == "OKX", "OKX fixture provider is invalid")
    _require(metadata["instrument_id"] == "BTC-USDT", "OKX fixture instrument is invalid")
    _require(metadata["bar"] == "1Dutc", "OKX fixture timeframe is invalid")
    _require(
        metadata["confirmed_only"] is True,
        "OKX fixture must contain confirmed candles only",
    )

    for key in (
        "fixture_closes_sha256",
        "fixture_timestamps_sha256",
        "source_artifact_sha256",
        "source_normalized_csv_sha256",
        "source_raw_pages_sha256",
    ):
        _require(_is_sha256(metadata[key]), f"OKX fixture metadata has invalid {key}")
    _require(
        len(str(metadata["source_head_sha"])) == 40
        and set(str(metadata["source_head_sha"]).lower()) <= _HEX_DIGITS,
        "OKX fixture source commit is invalid",
    )
    _require(int(metadata["source_artifact_id"]) > 0, "OKX fixture artifact id is invalid")
    _require(
        int(metadata["source_workflow_run_id"]) > 0,
        "OKX fixture workflow id is invalid",
    )

    actual_sha256 = hashlib.sha256(_CLOSES_PATH.read_bytes()).hexdigest()
    _require(
        metadata["fixture_closes_sha256"] == actual_sha256,
        "OKX regression fixture hash does not match its provenance metadata",
    )

    closes = json.loads(_CLOSES_PATH.read_text(encoding="utf-8"))
    observations = int(metadata["observations"])
    _require(
        isinstance(closes, list),
        "OKX regression fixture must contain a close-price list",
    )
    _require(observations > 0, "OKX regression fixture observation count must be positive")
    _require(
        len(closes) == observations,
        "OKX regression fixture observation count is invalid",
    )

    timestamp_ms = _load_timestamp_milliseconds(observations)
    index = pd.DatetimeIndex(pd.to_datetime(timestamp_ms, unit="ms", utc=True), name="timestamp")
    _require(not index.has_duplicates, "OKX fixture timestamps must be unique")
    _require(index.is_monotonic_increasing, "OKX fixture timestamps must be increasing")
    if len(index) > 1:
        deltas = index.to_series().diff().iloc[1:]
        _require(
            deltas.eq(pd.Timedelta(days=1)).all(),
            "OKX fixture timestamps must have exact daily cadence",
        )

    start = pd.Timestamp(metadata["start"])
    end = pd.Timestamp(metadata["end"])
    _require(
        start.tzinfo is not None and end.tzinfo is not None,
        "OKX fixture timestamps must be timezone-aware",
    )
    _require(
        start.utcoffset() == pd.Timedelta(0) and end.utcoffset() == pd.Timedelta(0),
        "OKX fixture timestamps must be UTC",
    )
    _require(index[0] == start, "OKX regression fixture start timestamp is invalid")
    _require(index[-1] == end, "OKX regression fixture end timestamp is invalid")

    return validate_prices(
        pd.Series(closes, index=index, name="close"),
        minimum_rows=observations,
    )


@pytest.fixture(scope="session")
def btc_usdt_prices() -> pd.Series:
    """Load immutable public OKX BTC-USDT closes and timestamps with verified provenance."""

    return _load_btc_usdt_prices()
