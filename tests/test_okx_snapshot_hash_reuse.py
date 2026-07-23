from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import gpt_quant.okx as okx_module
from gpt_quant.okx import fetch_okx_history_candles, write_okx_snapshot

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"


def _real_rows() -> list[list[str]]:
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    rows_bytes = _ROWS_PATH.read_bytes()
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert hashlib.sha256(rows_bytes).hexdigest() == metadata["fixture_rows_sha256"]
    return [list(row) for row in json.loads(rows_bytes)]


def test_fetch_reuses_canonical_snapshot_bytes_without_changing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _real_rows()
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

    def getter(url: str, timeout: float) -> dict[str, object]:
        return {"code": "0", "msg": "", "data": rows}

    snapshot = fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        limit=len(rows),
        max_pages=1,
        pause_seconds=0.0,
        get_json=getter,
    )

    assert csv_calls == 1
    assert json_calls == 2
    assert snapshot.metadata["normalized_csv_sha256"] == snapshot._source_normalized_csv_sha256
    assert snapshot.metadata["raw_pages_sha256"] == snapshot._source_raw_pages_sha256

    paths = write_okx_snapshot(snapshot, tmp_path / "snapshot")
    assert hashlib.sha256(paths["candles"].read_bytes()).hexdigest() == snapshot.metadata[
        "normalized_csv_sha256"
    ]
    assert hashlib.sha256(paths["raw"].read_bytes()).hexdigest() == snapshot.metadata[
        "raw_pages_sha256"
    ]
