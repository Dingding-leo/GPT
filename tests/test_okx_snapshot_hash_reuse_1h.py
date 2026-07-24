from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import gpt_quant.okx as okx_module
from gpt_quant.okx import fetch_okx_history_candles

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT"
_RAW_PATH = _FIXTURE_DIR / "okx-BTC-USDT-1H.raw.json"
_EXPECTED_RAW_SHA256 = "ef28063391f06d6d48e435c51f71b96ef0be6acd1d1fbdd01ead4c91f4338db8"


def test_real_okx_one_hour_fetch_reuses_each_canonical_payload_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_bytes = _RAW_PATH.read_bytes()
    assert hashlib.sha256(raw_bytes).hexdigest() == _EXPECTED_RAW_SHA256
    evidence_pages = json.loads(raw_bytes)
    assert len(evidence_pages) == 1
    payload = evidence_pages[0]["payload"]

    csv_calls = 0
    json_calls = 0
    canonical_csv = okx_module._canonical_csv_bytes
    canonical_json = okx_module._canonical_json_bytes

    def count_csv(frame: object) -> bytes:
        nonlocal csv_calls
        csv_calls += 1
        return canonical_csv(frame)

    def count_json(value: object) -> bytes:
        nonlocal json_calls
        json_calls += 1
        return canonical_json(value)

    monkeypatch.setattr(okx_module, "_canonical_csv_bytes", count_csv)
    monkeypatch.setattr(okx_module, "_canonical_json_bytes", count_json)

    snapshot = fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1H",
        start="2026-07-23T23:00:00Z",
        end="2026-07-24T01:00:00Z",
        limit=4,
        max_pages=1,
        pause_seconds=0.0,
        get_json=lambda url, timeout: payload,
    )

    assert len(snapshot.candles) == 3
    assert snapshot.candles["confirm"].eq("1").all()
    assert csv_calls == 1
    assert json_calls == 2
    assert snapshot.metadata["normalized_csv_sha256"] == snapshot._source_normalized_csv_sha256
    assert snapshot.metadata["raw_pages_sha256"] == snapshot._source_raw_pages_sha256
