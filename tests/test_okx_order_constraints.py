from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from gpt_quant.okx_instruments import fetch_okx_spot_instrument_snapshot
from gpt_quant.okx_live import OKXServerTimeSample
from gpt_quant.okx_order_constraints import validate_okx_spot_order_quantity

_FIXTURE_DIR = Path(__file__).parent / "fixtures/okx/public_instruments_btc_usdt_20251125"


def _real_okx_response_bytes() -> bytes:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    response_bytes = (_FIXTURE_DIR / "response.json").read_bytes()
    assert hashlib.sha256(response_bytes).hexdigest() == metadata["fixture_sha256"]
    return response_bytes


def _response_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _clock(*values: datetime):
    iterator = iter(values)
    return lambda: next(iterator)


def _snapshot(
    response_bytes: bytes | None = None,
    *,
    midpoint_clock_skew_ms: int = 0,
):
    started = datetime(2026, 7, 24, 0, 0, tzinfo=UTC)
    received = started + timedelta(milliseconds=125)
    local_started = received + timedelta(milliseconds=1)
    local_received = local_started + timedelta(milliseconds=100)
    midpoint = local_started + (local_received - local_started) / 2
    exchange_observed = midpoint + timedelta(milliseconds=midpoint_clock_skew_ms)
    sample = OKXServerTimeSample(
        base_url="https://www.okx.com",
        endpoint="/api/v5/public/time",
        local_request_started_utc=pd.Timestamp(local_started),
        local_response_received_utc=pd.Timestamp(local_received),
        server_time_utc=pd.Timestamp(exchange_observed),
        round_trip_seconds=0.1,
        midpoint_clock_skew_seconds=(exchange_observed - midpoint).total_seconds(),
    )
    return fetch_okx_spot_instrument_snapshot(
        inst_id="BTC-USDT",
        server_time_sample=sample,
        get_bytes=lambda _url, _timeout: response_bytes or _real_okx_response_bytes(),
        now=_clock(started, received),
    )


def test_real_okx_quantity_gate_rejects_below_minimum_off_lot_and_stale_orders() -> None:
    snapshot = _snapshot()
    submitted = snapshot.server_time_response_received_utc + timedelta(milliseconds=500)

    assert (
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=submitted,
            maximum_snapshot_age_ms=1_000,
            base_quantity="0.00001",
        )
        == "0.00001"
    )

    with pytest.raises(ValueError, match="below the OKX minimum"):
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=submitted,
            maximum_snapshot_age_ms=1_000,
            base_quantity="0.00000999",
        )

    with pytest.raises(ValueError, match="exact multiple of the OKX lot size"):
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=submitted,
            maximum_snapshot_age_ms=1_000,
            base_quantity="0.000010005",
        )

    with pytest.raises(ValueError, match="stale at order submission"):
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=snapshot.response_received_utc + timedelta(milliseconds=1_001),
            maximum_snapshot_age_ms=1_000,
            base_quantity="0.00001",
        )


@pytest.mark.parametrize("midpoint_clock_skew_ms", [100, -100])
def test_quantity_gate_uses_local_receipt_age_under_bounded_clock_skew(
    midpoint_clock_skew_ms: int,
) -> None:
    snapshot = _snapshot(midpoint_clock_skew_ms=midpoint_clock_skew_ms)
    submitted = snapshot.server_time_response_received_utc + timedelta(milliseconds=1)

    assert (
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=submitted,
            maximum_snapshot_age_ms=125,
            base_quantity="0.00001",
        )
        == "0.00001"
    )


@pytest.mark.parametrize("midpoint_clock_skew_ms", [100, -100])
def test_pending_change_uses_conservative_exchange_clock_cutoff(
    midpoint_clock_skew_ms: int,
) -> None:
    payload = json.loads(_real_okx_response_bytes())
    base_snapshot = _snapshot(midpoint_clock_skew_ms=midpoint_clock_skew_ms)
    effective_at = base_snapshot.exchange_observed_at_utc + timedelta(seconds=1)
    payload["data"][0]["upcChg"] = [
        {
            "param": "minSz",
            "newValue": "0.0001",
            "effTime": str(int(effective_at.timestamp() * 1_000)),
        }
    ]
    snapshot = _snapshot(
        _response_bytes(payload),
        midpoint_clock_skew_ms=midpoint_clock_skew_ms,
    )
    assert snapshot.valid_until_utc == effective_at

    local_cutoff = effective_at - timedelta(
        seconds=snapshot.midpoint_clock_skew_seconds + snapshot.server_round_trip_seconds / 2
    )
    assert (
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=local_cutoff - timedelta(milliseconds=1),
            maximum_snapshot_age_ms=2_000,
            base_quantity="0.00001",
        )
        == "0.00001"
    )
    with pytest.raises(ValueError, match="no longer valid at order submission"):
        validate_okx_spot_order_quantity(
            snapshot,
            submitted_at_utc=local_cutoff,
            maximum_snapshot_age_ms=2_000,
            base_quantity="0.00001",
        )
