from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.okx_execution_quote_replay import (
    ReconstructableOKXTopOfBookEvidence,
    fetch_reconstructable_okx_top_of_book,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "order-book-btc-usdt-docs-20210826"
_RESPONSE_PATH = _FIXTURE_DIR / "response.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_INSTRUMENT_SNAPSHOT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"


def _fixture_response() -> bytes:
    response = _RESPONSE_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["source_kind"] == "official_documentation_response_example"
    assert metadata["response_sha256"] == _EXPECTED_RESPONSE_SHA256
    assert hashlib.sha256(response).hexdigest() == _EXPECTED_RESPONSE_SHA256
    return response


def _clock(*values: str):
    timestamps: Iterator[datetime] = iter(
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        for value in values
    )
    return lambda: next(timestamps)


def _server_time_getter(url: str, timeout: float) -> dict[str, object]:
    assert url == "https://example.test/api/v5/public/time"
    assert timeout == 20.0
    return {"code": "0", "msg": "", "data": [{"ts": "1629966436500"}]}


def _evidence() -> ReconstructableOKXTopOfBookEvidence:
    return fetch_reconstructable_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
        base_url="https://example.test",
        maximum_quote_age_ms=200,
        get_bytes=lambda url, timeout: _fixture_response(),
        get_json=_server_time_getter,
        now=_clock(
            "2021-08-26T08:27:16.420000Z",
            "2021-08-26T08:27:16.450000Z",
            "2021-08-26T08:27:16.460000Z",
            "2021-08-26T08:27:16.540000Z",
        ),
    )


def test_reconstructable_quote_evidence_round_trips_current_observation_contract() -> None:
    evidence = _evidence()
    replayed = ReconstructableOKXTopOfBookEvidence.from_json_bytes(evidence.to_json_bytes())

    assert replayed == evidence
    assert replayed.server_time_request_started_utc == datetime(
        2021, 8, 26, 8, 27, 16, 460_000, tzinfo=UTC
    )
    assert replayed.observation.server_time_request_started_utc == (
        replayed.server_time_request_started_utc
    )
    assert replayed.observation.server_time_endpoint == "/api/v5/public/time"
    assert replayed.observation.max_request_round_trip_seconds == 2.0
    assert replayed.observation.max_server_round_trip_seconds == 2.0
    assert replayed.observation.max_abs_midpoint_clock_skew_seconds == 5.0
    assert replayed.observation.source_response_sha256 == _EXPECTED_RESPONSE_SHA256
    assert replayed.observation.quote.instrument_snapshot_sha256 == _INSTRUMENT_SNAPSHOT_SHA256
    assert replayed.timeout_seconds == 20.0
    assert len(replayed.evidence_id) == 64


def test_reconstructable_quote_evidence_rejects_duplicate_timing_policy() -> None:
    evidence = _evidence()

    with pytest.raises(ValueError, match="request start does not match observation"):
        replace(
            evidence,
            server_time_request_started_utc=evidence.server_time_request_started_utc
            + timedelta(microseconds=1),
        )
    with pytest.raises(ValueError, match="books round-trip policy does not match observation"):
        replace(evidence, max_request_round_trip_seconds=3.0)
    with pytest.raises(ValueError, match="server round-trip policy does not match observation"):
        replace(evidence, max_server_round_trip_seconds=3.0)
    with pytest.raises(ValueError, match="clock-skew policy does not match observation"):
        replace(evidence, max_abs_midpoint_clock_skew_seconds=6.0)


def test_reconstructable_quote_evidence_rejects_forged_observation_timing() -> None:
    evidence = _evidence()

    with pytest.raises(ValueError, match="round trip"):
        replace(
            evidence.observation,
            server_time_response_received_utc=datetime(2026, 7, 23, 21, 0, 0, tzinfo=UTC),
        )
