from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.okx_execution_quote import fetch_okx_top_of_book
from gpt_quant.okx_execution_quote_replay import ReconstructableOKXTopOfBookEvidence

_FIXTURE_DIR = (
    Path(__file__).parent / "fixtures" / "okx" / "order-book-btc-usdt-docs-20210826"
)
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


def test_fresh_quote_survives_bounded_slow_local_clock() -> None:
    observation = fetch_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
        base_url="https://example.test",
        maximum_quote_age_ms=200,
        max_abs_midpoint_clock_skew_seconds=0.2,
        get_bytes=lambda url, timeout: _fixture_response(),
        get_json=lambda url, timeout: {
            "code": "0",
            "msg": "",
            "data": [{"ts": "1629966436500"}],
        },
        now=_clock(
            "2021-08-26T08:27:16.320000Z",
            "2021-08-26T08:27:16.350000Z",
            "2021-08-26T08:27:16.360000Z",
            "2021-08-26T08:27:16.440000Z",
        ),
    )

    assert observation.source_response_sha256 == _EXPECTED_RESPONSE_SHA256
    assert observation.midpoint_clock_skew_seconds == pytest.approx(0.1)
    assert observation.quote.observed_at_utc == datetime(
        2021, 8, 26, 8, 27, 16, 396_000, tzinfo=UTC
    )
    assert observation.quote.received_at_utc == observation.response_received_utc + timedelta(
        seconds=observation.midpoint_clock_skew_seconds
    )

    evidence = ReconstructableOKXTopOfBookEvidence(observation=observation)
    assert ReconstructableOKXTopOfBookEvidence.from_json_bytes(evidence.to_json_bytes()) == evidence
