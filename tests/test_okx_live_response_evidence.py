from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import build_okx_completed_bar_cutoff, fetch_okx_history_candles
from gpt_quant.okx_live_response_evidence import (
    build_okx_live_timing_response_evidence,
    read_okx_live_timing_response_evidence,
    sample_okx_server_time_with_response,
    write_okx_live_timing_response_evidence,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_SERVER_TIME_PAYLOAD = {
    "code": "0",
    "msg": "",
    "data": [{"ts": "1784635200100"}],
}


def _canonical_json_bytes(value: dict[str, object]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def _real_okx_rows() -> list[list[str]]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["fixture_rows_sha256"] == _EXPECTED_FIXTURE_SHA256
    assert hashlib.sha256(rows_bytes).hexdigest() == _EXPECTED_FIXTURE_SHA256
    return json.loads(rows_bytes)


def _download():
    rows = _real_okx_rows()

    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert "instId=BTC-USDT" in url
        assert "bar=1Dutc" in url
        assert timeout == 20.0
        return {"code": "0", "msg": "", "data": [list(row) for row in rows]}

    return fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        base_url="https://www.okx.com",
        limit=100,
        max_pages=1,
        pause_seconds=0.0,
        as_of="2026-07-21T11:59:59+00:00",
        get_json=fake_getter,
    )


def _clock(*values: str):
    timestamps: Iterator[pd.Timestamp] = iter(pd.Timestamp(value) for value in values)
    return lambda: next(timestamps)


def _observation():
    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert url == "https://www.okx.com/api/v5/public/time"
        assert timeout == 20.0
        return json.loads(json.dumps(_SERVER_TIME_PAYLOAD))

    return sample_okx_server_time_with_response(
        base_url="https://www.okx.com",
        get_json=fake_getter,
        now=_clock(
            "2026-07-21T12:00:00.000+00:00",
            "2026-07-21T12:00:00.200+00:00",
        ),
    )


def _cutoff(observation):
    return build_okx_completed_bar_cutoff(
        _download(),
        server_time_sample=observation.sample,
    )


def test_real_okx_cutoff_persists_reconstructable_public_time_response(tmp_path) -> None:
    observation = _observation()
    cutoff = _cutoff(observation)
    output = tmp_path / "okx-live-timing-response.json"

    path, digest = write_okx_live_timing_response_evidence(
        output,
        observation=observation,
        cutoff=cutoff,
    )
    second_path, second_digest = write_okx_live_timing_response_evidence(
        output,
        observation=observation,
        cutoff=cutoff,
    )
    restored = read_okx_live_timing_response_evidence(path, expected_sha256=digest)

    assert second_path == path
    assert second_digest == digest
    assert restored == build_okx_live_timing_response_evidence(
        observation=observation,
        cutoff=cutoff,
    )
    assert restored["provider"] == "OKX"
    assert restored["instrument_id"] == "BTC-USDT"
    assert restored["bar"] == "1Dutc"
    assert restored["server_time_response"] == _SERVER_TIME_PAYLOAD
    assert (
        restored["server_time_response_sha256"]
        == hashlib.sha256(_canonical_json_bytes(_SERVER_TIME_PAYLOAD)).hexdigest()
    )
    assert restored["exchange_server_time_utc"] == "2026-07-21T12:00:00.100000+00:00"
    assert restored["signal_not_before_utc"] == "2026-07-21T12:00:00.200000+00:00"


def test_public_time_response_must_match_validated_sample() -> None:
    observation = _observation()
    different_response = {
        "code": "0",
        "msg": "",
        "data": [{"ts": "1784635200101"}],
    }

    with pytest.raises(ValueError, match="does not match the validated server-time sample"):
        build_okx_live_timing_response_evidence(
            observation=replace(
                observation,
                response_json=_canonical_json_bytes(different_response),
            ),
            cutoff=_cutoff(observation),
        )


@pytest.mark.parametrize(
    "response_json, message",
    [
        (
            b'{"code":"0","code":"0","data":[{"ts":"1784635200100"}],"msg":""}\n',
            "duplicate field",
        ),
        (
            json.dumps(_SERVER_TIME_PAYLOAD, indent=2).encode("utf-8"),
            "canonical JSON encoding",
        ),
    ],
)
def test_public_time_response_rejects_ambiguous_encodings(
    response_json: bytes,
    message: str,
) -> None:
    observation = _observation()

    with pytest.raises(ValueError, match=message):
        build_okx_live_timing_response_evidence(
            observation=replace(observation, response_json=response_json),
            cutoff=_cutoff(observation),
        )


def test_reader_rejects_self_consistent_exchange_timestamp_rewrite(tmp_path) -> None:
    observation = _observation()
    output = tmp_path / "okx-live-timing-response.json"
    write_okx_live_timing_response_evidence(
        output,
        observation=observation,
        cutoff=_cutoff(observation),
    )

    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["server_time_response"]["data"][0]["ts"] = "1784635200101"
    tampered_response = _canonical_json_bytes(tampered["server_time_response"])
    tampered["server_time_response_sha256"] = hashlib.sha256(tampered_response).hexdigest()
    tampered_payload = _canonical_json_bytes(tampered)
    output.write_bytes(tampered_payload)

    with pytest.raises(ValueError, match="does not match the public-time response"):
        read_okx_live_timing_response_evidence(
            output,
            expected_sha256=hashlib.sha256(tampered_payload).hexdigest(),
        )
