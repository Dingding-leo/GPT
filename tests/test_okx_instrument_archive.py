from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant.okx_instrument_archive import write_okx_spot_instrument_observation
from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample

_FIXTURE_DIR = Path(__file__).parent / "fixtures/okx/public_instruments_btc_usdt_20251125"


def _real_okx_response_bytes() -> bytes:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    response_bytes = (_FIXTURE_DIR / "response.json").read_bytes()
    assert hashlib.sha256(response_bytes).hexdigest() == metadata["fixture_sha256"]
    return response_bytes


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _snapshot(started: datetime):
    received = started + timedelta(milliseconds=125)
    server_started = received + timedelta(milliseconds=1)
    server_received = server_started + timedelta(milliseconds=100)
    server_time = server_started + timedelta(milliseconds=50)
    midpoint = server_started + (server_received - server_started) / 2
    sample = OKXServerTimeSample(
        base_url="https://www.okx.com",
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp(server_started),
        local_response_received_utc=pd.Timestamp(server_received),
        server_time_utc=pd.Timestamp(server_time),
        round_trip_seconds=0.1,
        midpoint_clock_skew_seconds=(server_time - midpoint).total_seconds(),
    )
    return fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        server_time_sample=sample,
        get_bytes=lambda _url, _timeout: _real_okx_response_bytes(),
        now=_clock(started, received),
    )


def test_distinct_forward_observations_coexist_by_content_address(tmp_path: Path) -> None:
    first = _snapshot(datetime(2026, 7, 24, 0, 0, tzinfo=UTC))
    second = _snapshot(datetime(2026, 7, 24, 0, 1, tzinfo=UTC))

    first_paths = write_okx_spot_instrument_observation(first, tmp_path)
    second_paths = write_okx_spot_instrument_observation(second, tmp_path)

    assert first.metadata_sha256 != second.metadata_sha256
    assert first_paths != second_paths
    assert first.metadata_sha256 in first_paths["metadata"].name
    assert second.metadata_sha256 in second_paths["metadata"].name
    assert first_paths["raw"].read_bytes() == second_paths["raw"].read_bytes()
    assert first_paths["metadata"].read_bytes() != second_paths["metadata"].read_bytes()
    assert len(tuple(tmp_path.iterdir())) == 4
    assert write_okx_spot_instrument_observation(first, tmp_path) == first_paths


def test_tampered_observation_fails_without_touching_other_snapshot(tmp_path: Path) -> None:
    first = _snapshot(datetime(2026, 7, 24, 0, 0, tzinfo=UTC))
    second = _snapshot(datetime(2026, 7, 24, 0, 1, tzinfo=UTC))
    first_paths = write_okx_spot_instrument_observation(first, tmp_path)
    second_paths = write_okx_spot_instrument_observation(second, tmp_path)
    second_metadata = second_paths["metadata"].read_bytes()

    first_paths["metadata"].write_text("tampered\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="conflicting"):
        write_okx_spot_instrument_observation(first, tmp_path)

    assert second_paths["metadata"].read_bytes() == second_metadata
