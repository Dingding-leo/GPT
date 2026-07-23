from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
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
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC) for value in values
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


def test_reconstructable_quote_evidence_round_trips_real_okx_extract() -> None:
    evidence = _evidence()
    replayed = ReconstructableOKXTopOfBookEvidence.from_json_bytes(evidence.to_json_bytes())

    assert replayed == evidence
    assert replayed.server_time_request_started_utc == datetime(
        2021, 8, 26, 8, 27, 16, 460_000, tzinfo=UTC
    )
    assert replayed.observation.source_response_sha256 == _EXPECTED_RESPONSE_SHA256
    assert replayed.observation.quote.instrument_snapshot_sha256 == _INSTRUMENT_SNAPSHOT_SHA256
    assert replayed.timeout_seconds == 20.0
    assert replayed.max_request_round_trip_seconds == 2.0
    assert replayed.max_server_round_trip_seconds == 2.0
    assert replayed.max_abs_midpoint_clock_skew_seconds == 5.0
    assert len(replayed.evidence_id) == 64


def test_reconstructable_quote_evidence_rejects_forged_timing_and_policy() -> None:
    evidence = _evidence()

    with pytest.raises(ValueError, match="server-time round trip does not match"):
        replace(
            evidence,
            server_time_request_started_utc=datetime(
                2021, 8, 26, 8, 27, 16, 470_000, tzinfo=UTC
            ),
        )

    forged_observation = replace(
        evidence.observation,
        server_time_response_received_utc=datetime(2026, 7, 23, 21, 0, 0, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="server-time round trip does not match"):
        replace(evidence, observation=forged_observation)

    with pytest.raises(ValueError, match="server-time round trip exceeds replay policy"):
        replace(evidence, max_server_round_trip_seconds=0.01)

    with pytest.raises(ValueError, match="midpoint clock skew exceeds replay policy"):
        skewed_observation = replace(
            evidence.observation,
            exchange_time_observed_utc=datetime(
                2021, 8, 26, 8, 27, 16, 501_000, tzinfo=UTC
            ),
            midpoint_clock_skew_seconds=0.001,
        )
        replace(
            evidence,
            observation=skewed_observation,
            max_abs_midpoint_clock_skew_seconds=0.0005,
        )
