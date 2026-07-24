from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant.okx_execution_quote import fetch_okx_top_of_book
from gpt_quant.okx_execution_quote_replay import ReconstructableOKXTopOfBookEvidence

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "order-book-btc-usdt-docs-20210826"
_RESPONSE_PATH = _FIXTURE_DIR / "response.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_RESPONSE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_EXPECTED_SERVER_TIME_RESPONSE_SHA256 = (
    "2ab44b9abd247acb72cf79b22b30e14c4e80cc00a96384a4535b31a37f6dfeb0"
)
_INSTRUMENT_SNAPSHOT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_SERVER_TIME_RESPONSE = b'{"code":"0","msg":"","data":[{"ts":"1629966436500"}]}'


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


def _observation():
    return fetch_okx_top_of_book(
        instrument_id="BTC-USDT",
        instrument_snapshot_sha256=_INSTRUMENT_SNAPSHOT_SHA256,
        base_url="https://test.okx.com",
        maximum_quote_age_ms=200,
        get_bytes=lambda url, timeout: _fixture_response(),
        get_server_time_bytes=lambda url, timeout: _SERVER_TIME_RESPONSE,
        now=_clock(
            "2021-08-26T08:27:16.420000Z",
            "2021-08-26T08:27:16.450000Z",
            "2021-08-26T08:27:16.460000Z",
            "2021-08-26T08:27:16.540000Z",
        ),
    )


def _canonical_payload(evidence: ReconstructableOKXTopOfBookEvidence) -> dict[str, object]:
    return json.loads(evidence.to_json_bytes())


def _serialized(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        + b"\n"
    )


def test_top_of_book_replay_round_trips_complete_real_okx_evidence() -> None:
    evidence = ReconstructableOKXTopOfBookEvidence(observation=_observation())
    replayed = ReconstructableOKXTopOfBookEvidence.from_json_bytes(evidence.to_json_bytes())

    assert replayed == evidence
    assert replayed.schema_version == 2
    assert replayed.observation.raw_response_json == _fixture_response()
    assert replayed.observation.source_response_sha256 == _EXPECTED_RESPONSE_SHA256
    assert replayed.observation.raw_server_time_response_json == _SERVER_TIME_RESPONSE
    assert replayed.observation.server_time_response_sha256 == _EXPECTED_SERVER_TIME_RESPONSE_SHA256
    payload = _canonical_payload(replayed)
    assert payload["server_time_response_sha256"] == _EXPECTED_SERVER_TIME_RESPONSE_SHA256
    assert replayed.observation.quote.instrument_snapshot_sha256 == _INSTRUMENT_SNAPSHOT_SHA256
    assert replayed.observation.server_time_request_started_utc == datetime(
        2021, 8, 26, 8, 27, 16, 460_000, tzinfo=UTC
    )
    assert replayed.observation.max_request_round_trip_seconds == 2.0
    assert replayed.observation.max_server_round_trip_seconds == 2.0
    assert replayed.observation.max_abs_midpoint_clock_skew_seconds == 5.0
    assert len(replayed.evidence_id) == 64


def test_top_of_book_replay_rejects_legacy_version_for_new_source_layout() -> None:
    evidence = ReconstructableOKXTopOfBookEvidence(observation=_observation())
    payload = _canonical_payload(evidence)
    payload["schema_version"] = 1

    with pytest.raises(ValueError, match="unsupported OKX quote replay schema"):
        ReconstructableOKXTopOfBookEvidence.from_json_bytes(_serialized(payload))


def test_top_of_book_replay_rejects_server_time_hash_mismatch() -> None:
    evidence = ReconstructableOKXTopOfBookEvidence(observation=_observation())
    payload = _canonical_payload(evidence)
    payload["raw_server_time_response_json_utf8"] = (
        '{"code":"0","msg":"","data":[{"ts":"1629966436499"}]}'
    )

    with pytest.raises(ValueError, match="SHA-256 does not match its bytes"):
        ReconstructableOKXTopOfBookEvidence.from_json_bytes(_serialized(payload))


def test_top_of_book_replay_rejects_forged_timing_envelope() -> None:
    evidence = ReconstructableOKXTopOfBookEvidence(observation=_observation())
    payload = _canonical_payload(evidence)
    payload["server_time_response_received_utc"] = "2026-07-23T21:00:00.000000Z"

    with pytest.raises(ValueError, match="round trip does not match its timestamps"):
        ReconstructableOKXTopOfBookEvidence.from_json_bytes(_serialized(payload))


def test_top_of_book_replay_rejects_altered_server_time_source_bytes() -> None:
    evidence = ReconstructableOKXTopOfBookEvidence(observation=_observation())
    payload = _canonical_payload(evidence)
    payload["raw_server_time_response_json_utf8"] = (
        '{"code":"0","msg":"","data":[{"ts":"1629966436499"}]}'
    )
    payload["server_time_response_sha256"] = hashlib.sha256(
        payload["raw_server_time_response_json_utf8"].encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValueError, match="does not reproduce the exchange timestamp"):
        ReconstructableOKXTopOfBookEvidence.from_json_bytes(_serialized(payload))


def test_top_of_book_replay_rejects_weakened_policy_and_altered_identity() -> None:
    evidence = ReconstructableOKXTopOfBookEvidence(observation=_observation())
    weakened = _canonical_payload(evidence)
    weakened["max_server_round_trip_seconds"] = "0.01"

    with pytest.raises(ValueError, match="round trip exceeds the live cutoff bound"):
        ReconstructableOKXTopOfBookEvidence.from_json_bytes(_serialized(weakened))

    altered_id = _canonical_payload(evidence)
    altered_id["evidence_id"] = "0" * 64
    with pytest.raises(ValueError, match="ID does not match"):
        ReconstructableOKXTopOfBookEvidence.from_json_bytes(_serialized(altered_id))


def test_top_of_book_replay_rejects_duplicate_and_noncanonical_json() -> None:
    evidence = ReconstructableOKXTopOfBookEvidence(observation=_observation())
    canonical = evidence.to_json_bytes()
    duplicate = canonical.replace(
        b'{"base_url":',
        b'{"base_url":"https://test.okx.com","base_url":',
        1,
    )
    with pytest.raises(ValueError, match="duplicate field 'base_url'"):
        ReconstructableOKXTopOfBookEvidence.from_json_bytes(duplicate)

    pretty = json.dumps(json.loads(canonical), indent=2, sort_keys=True).encode("utf-8") + b"\n"
    with pytest.raises(ValueError, match="canonical encoding"):
        ReconstructableOKXTopOfBookEvidence.from_json_bytes(pretty)
