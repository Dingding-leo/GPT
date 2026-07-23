from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from gpt_quant.okx_instruments import (
    fetch_okx_spot_instrument_snapshot,
    write_okx_spot_instrument_snapshot,
)
from gpt_quant.okx_live import OKXServerTimeSample

_FIXTURE_DIR = Path(__file__).parent / "fixtures/okx/public_instruments_btc_usdt_20251125"


def _real_okx_response_bytes() -> bytes:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    response_bytes = (_FIXTURE_DIR / "response.json").read_bytes()
    assert hashlib.sha256(response_bytes).hexdigest() == metadata["fixture_sha256"]
    return response_bytes


def _real_okx_payload() -> dict[str, Any]:
    return json.loads(_real_okx_response_bytes())


def _response_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _server_time_sample(
    *,
    instrument_received: datetime,
    exchange_observed: datetime | None = None,
    base_url: str = "https://www.okx.com",
) -> OKXServerTimeSample:
    local_started = instrument_received + timedelta(milliseconds=1)
    local_received = local_started + timedelta(milliseconds=100)
    server_time = exchange_observed or local_started + timedelta(milliseconds=50)
    midpoint = local_started + (local_received - local_started) / 2
    return OKXServerTimeSample(
        base_url=base_url,
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp(local_started),
        local_response_received_utc=pd.Timestamp(local_received),
        server_time_utc=pd.Timestamp(server_time),
        round_trip_seconds=0.1,
        midpoint_clock_skew_seconds=(server_time - midpoint).total_seconds(),
    )


def _snapshot(
    payload: dict[str, Any] | None = None,
    *,
    response_bytes: bytes | None = None,
):
    started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    received = started + timedelta(milliseconds=125)
    requests: list[tuple[str, float]] = []

    raw_response = (
        response_bytes
        if response_bytes is not None
        else _response_bytes(payload)
        if payload is not None
        else _real_okx_response_bytes()
    )

    def get_bytes(url: str, timeout: float):
        requests.append((url, timeout))
        return raw_response

    snapshot = fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        server_time_sample=_server_time_sample(instrument_received=received),
        get_bytes=get_bytes,
        now=_clock(started, received),
    )
    return snapshot, requests


def test_real_okx_spot_constraints_are_exact_and_hash_bound(tmp_path: Path) -> None:
    snapshot, requests = _snapshot()

    assert requests == [
        (
            "https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT",
            20.0,
        )
    ]
    assert snapshot.state == "live"
    assert snapshot.tick_size == "0.1"
    assert snapshot.lot_size == "0.00000001"
    assert snapshot.minimum_order_size_base == "0.00001"
    assert snapshot.raw_response_json == _real_okx_response_bytes()
    assert (
        snapshot.raw_response_sha256
        == "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
    )
    assert snapshot.tick_size_decimal.is_finite()
    assert snapshot.valid_until_utc is None
    assert snapshot.exchange_observed_at_utc > snapshot.response_received_utc

    paths = write_okx_spot_instrument_snapshot(snapshot, tmp_path)
    assert hashlib.sha256(paths["raw"].read_bytes()).hexdigest() == snapshot.raw_response_sha256
    assert hashlib.sha256(paths["metadata"].read_bytes()).hexdigest() == snapshot.metadata_sha256
    metadata = json.loads(paths["metadata"].read_bytes())
    assert metadata["minimum_order_size_base"] == "0.00001"
    assert metadata["exchange_observed_at_utc"] == "2026-07-24T00:00:00.176000Z"
    assert metadata["server_round_trip_seconds"] == 0.1
    assert "minimum quote notional" in metadata["limitations"][0]

    assert write_okx_spot_instrument_snapshot(snapshot, tmp_path) == paths


def test_snapshot_fields_are_replayed_from_exact_provider_bytes() -> None:
    snapshot, _ = _snapshot()

    with pytest.raises(
        ValueError,
        match="tick_size does not match the exact OKX instrument response",
    ):
        replace(snapshot, tick_size="999999")


def test_duplicate_constraint_field_is_rejected_before_snapshot_creation() -> None:
    response_bytes = _real_okx_response_bytes()
    conflicting_response = response_bytes.replace(
        b'"tickSz":"0.1"',
        b'"tickSz":"999999","tickSz":"0.1"',
        1,
    )
    assert conflicting_response != response_bytes
    assert (
        hashlib.sha256(conflicting_response).hexdigest()
        != hashlib.sha256(response_bytes).hexdigest()
    )

    with pytest.raises(ValueError, match="duplicate field 'tickSz'"):
        _snapshot(response_bytes=conflicting_response)


def test_non_live_or_invalid_constraints_fail_closed() -> None:
    payload = _real_okx_payload()
    payload["data"][0]["state"] = "suspend"
    with pytest.raises(ValueError, match="not live"):
        _snapshot(payload)

    payload = _real_okx_payload()
    payload["data"][0]["tickSz"] = "0"
    with pytest.raises(ValueError, match="tickSz"):
        _snapshot(payload)

    payload = _real_okx_payload()
    payload["data"][0]["instId"] = "ETH-USDT"
    with pytest.raises(ValueError, match="requested inst_id"):
        _snapshot(payload)


def test_exchange_time_rejects_locally_future_but_already_effective_change() -> None:
    payload = _real_okx_payload()
    effective_at = datetime(2026, 7, 24, 5, 0, tzinfo=UTC)
    payload["data"][0]["upcChg"] = [
        {
            "param": "tickSz",
            "newValue": "0.01",
            "effTime": str(int(effective_at.timestamp() * 1_000)),
        }
    ]
    started = datetime(2026, 7, 24, 4, 59, 54, 900000, tzinfo=UTC)
    received = datetime(2026, 7, 24, 4, 59, 55, tzinfo=UTC)
    sample = _server_time_sample(
        instrument_received=received,
        exchange_observed=effective_at,
    )

    with pytest.raises(ValueError, match="already-effective"):
        fetch_okx_spot_instrument_snapshot(
            inst_id="BTC-USDT",
            server_time_sample=sample,
            get_bytes=lambda _url, _timeout: _response_bytes(payload),
            now=_clock(started, received),
        )


def test_server_time_must_follow_response_and_match_base_url() -> None:
    started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    received = started + timedelta(milliseconds=125)
    sample = _server_time_sample(instrument_received=started - timedelta(seconds=1))
    with pytest.raises(ValueError, match="sampled after"):
        fetch_okx_spot_instrument_snapshot(
            inst_id="BTC-USDT",
            server_time_sample=sample,
            get_bytes=lambda _url, _timeout: _real_okx_response_bytes(),
            now=_clock(started, received),
        )

    wrong_base = _server_time_sample(
        instrument_received=received,
        base_url="https://example.invalid",
    )
    with pytest.raises(ValueError, match="same base URL"):
        fetch_okx_spot_instrument_snapshot(
            inst_id="BTC-USDT",
            server_time_sample=wrong_base,
            get_bytes=lambda _url, _timeout: _real_okx_response_bytes(),
            now=_clock(started, received),
        )


def test_upcoming_constraint_change_bounds_snapshot_validity() -> None:
    payload = _real_okx_payload()
    effective_at = datetime(2026, 7, 25, 0, 0, tzinfo=UTC)
    payload["data"][0]["upcChg"] = [
        {
            "param": "tickSz",
            "newValue": "0.01",
            "effTime": str(int(effective_at.timestamp() * 1_000)),
        }
    ]

    snapshot, _ = _snapshot(payload)
    assert snapshot.valid_until_utc == effective_at
    assert len(snapshot.upcoming_changes) == 1
    change = snapshot.upcoming_changes[0]
    assert change.parameter == "tickSz"
    assert change.new_value == "0.01"
    assert change.effective_at_utc == effective_at


def test_conflicting_existing_snapshot_is_not_overwritten(tmp_path: Path) -> None:
    snapshot, _ = _snapshot()
    paths = write_okx_spot_instrument_snapshot(snapshot, tmp_path)
    paths["metadata"].write_text("conflict\n", encoding="utf-8")

    raw_bytes = paths["raw"].read_bytes()
    with pytest.raises(FileExistsError, match="conflicting"):
        write_okx_spot_instrument_snapshot(snapshot, tmp_path)
    assert paths["raw"].read_bytes() == raw_bytes
