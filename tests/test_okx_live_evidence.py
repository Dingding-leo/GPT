from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import (
    build_okx_completed_bar_cutoff,
    fetch_okx_history_candles,
    sample_okx_server_time,
)
from gpt_quant.okx_live_evidence import (
    build_okx_live_timing_evidence,
    read_okx_live_timing_evidence,
    write_okx_live_timing_evidence,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"


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


def _sample():
    def fake_getter(url: str, timeout: float) -> dict[str, object]:
        assert url == "https://www.okx.com/api/v5/public/time"
        assert timeout == 20.0
        return {"code": "0", "msg": "", "data": [{"ts": "1784635200100"}]}

    return sample_okx_server_time(
        base_url="https://www.okx.com",
        get_json=fake_getter,
        now=_clock(
            "2026-07-21T12:00:00.000+00:00",
            "2026-07-21T12:00:00.200+00:00",
        ),
    )


def _cutoff():
    return build_okx_completed_bar_cutoff(
        _download(),
        server_time_sample=_sample(),
    )


def test_real_okx_timing_evidence_is_canonical_immutable_and_hash_bound(tmp_path) -> None:
    output = tmp_path / "okx-live-timing.json"

    path, digest = write_okx_live_timing_evidence(
        output,
        sample=_sample(),
        cutoff=_cutoff(),
    )
    second_path, second_digest = write_okx_live_timing_evidence(
        output,
        sample=_sample(),
        cutoff=_cutoff(),
    )
    restored = read_okx_live_timing_evidence(path, expected_sha256=digest)

    assert second_path == path
    assert second_digest == digest
    assert restored == build_okx_live_timing_evidence(sample=_sample(), cutoff=_cutoff())
    assert restored["provider"] == "OKX"
    assert restored["instrument_id"] == "BTC-USDT"
    assert restored["bar"] == "1Dutc"
    assert restored["source_url"] == "https://www.okx.com/api/v5/public/time"
    assert restored["signal_not_before_utc"] == "2026-07-21T12:00:00.200000+00:00"


def test_real_okx_timing_evidence_rejects_tampering_and_cutoff_drift(tmp_path) -> None:
    output = tmp_path / "okx-live-timing.json"
    _, digest = write_okx_live_timing_evidence(
        output,
        sample=_sample(),
        cutoff=_cutoff(),
    )
    tampered = json.loads(output.read_text(encoding="utf-8"))
    tampered["signal_not_before_utc"] = "2026-07-21T00:00:00+00:00"
    output.write_text(json.dumps(tampered, sort_keys=True), encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        read_okx_live_timing_evidence(output, expected_sha256=digest)

    drifted = replace(
        _cutoff(),
        exchange_observed_at_utc=pd.Timestamp("2026-07-21T12:00:00.101+00:00"),
    )
    with pytest.raises(ValueError, match="not bound to the supplied OKX server time"):
        build_okx_live_timing_evidence(sample=_sample(), cutoff=drifted)
