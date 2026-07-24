from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from gpt_quant.okx import write_okx_snapshot
from gpt_quant.okx_1h import fetch_okx_one_hour_candles
from gpt_quant.okx_1h_forward_registry import (
    register_okx_one_hour_forward_snapshot,
    replay_okx_one_hour_forward_registry,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT"
_RAW_PATH = _FIXTURE_DIR / "okx-BTC-USDT-1H.raw.json"


def _fixture_response_bytes() -> bytes:
    pages = json.loads(_RAW_PATH.read_text(encoding="utf-8"))
    return base64.b64decode(pages[0]["raw_response_base64"], validate=True)


def _write_snapshot(path: Path, *, end: str, raw: bytes) -> None:
    snapshot = fetch_okx_one_hour_candles(
        inst_id="BTC-USDT",
        start="2026-07-23T23:00:00Z",
        end=end,
        pause_seconds=0.0,
        get_bytes=lambda url, timeout: raw,
    )
    write_okx_snapshot(snapshot, path)


def test_forward_registry_accepts_real_overlap_and_one_completed_append(
    tmp_path: Path,
) -> None:
    raw = _fixture_response_bytes()
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    registry = tmp_path / "registry"
    _write_snapshot(previous, end="2026-07-24T00:00:00Z", raw=raw)
    _write_snapshot(current, end="2026-07-24T01:00:00Z", raw=raw)

    first = register_okx_one_hour_forward_snapshot(
        previous,
        registry,
        inst_id="BTC-USDT",
    )
    second = register_okx_one_hour_forward_snapshot(
        current,
        registry,
        inst_id="BTC-USDT",
    )

    assert first["appended_observations"] == 2
    assert second["overlap_observations"] == 2
    assert second["appended_observations"] == 1
    assert second["appended_start_utc"] == "2026-07-24T01:00:00Z"
    assert len(replay_okx_one_hour_forward_registry(registry, inst_id="BTC-USDT")) == 2

    retry = register_okx_one_hour_forward_snapshot(
        current,
        registry,
        inst_id="BTC-USDT",
    )
    assert retry == second
    journal = registry / "BTC-USDT" / "okx-1h-forward-registry.jsonl"
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 2


def test_forward_registry_treats_same_window_reacquisition_as_idempotent(
    tmp_path: Path,
) -> None:
    raw = _fixture_response_bytes()
    original = tmp_path / "original"
    reacquired = tmp_path / "reacquired"
    registry = tmp_path / "registry"
    _write_snapshot(original, end="2026-07-24T00:00:00Z", raw=raw)
    _write_snapshot(reacquired, end="2026-07-24T00:00:00Z", raw=raw)

    metadata_path = reacquired / "okx-BTC-USDT-1H.metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["fetched_at_utc"] = "2026-07-24T05:00:00+00:00"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    first = register_okx_one_hour_forward_snapshot(
        original,
        registry,
        inst_id="BTC-USDT",
    )
    retry = register_okx_one_hour_forward_snapshot(
        reacquired,
        registry,
        inst_id="BTC-USDT",
    )

    assert retry == first
    journal = registry / "BTC-USDT" / "okx-1h-forward-registry.jsonl"
    assert len(journal.read_text(encoding="utf-8").splitlines()) == 1


def test_forward_registry_rejects_changed_completed_overlap_bar(tmp_path: Path) -> None:
    raw = _fixture_response_bytes()
    previous = tmp_path / "previous"
    mutated = tmp_path / "mutated"
    registry = tmp_path / "registry"
    _write_snapshot(previous, end="2026-07-24T00:00:00Z", raw=raw)
    register_okx_one_hour_forward_snapshot(previous, registry, inst_id="BTC-USDT")

    corrupted = raw.replace(b'"65096"', b'"65095"', 1)
    assert corrupted != raw
    _write_snapshot(mutated, end="2026-07-24T01:00:00Z", raw=corrupted)

    with pytest.raises(ValueError, match="changed a previously completed overlap bar"):
        register_okx_one_hour_forward_snapshot(
            mutated,
            registry,
            inst_id="BTC-USDT",
        )


def test_forward_registry_rejects_truncated_journal_record(tmp_path: Path) -> None:
    raw = _fixture_response_bytes()
    snapshot = tmp_path / "snapshot"
    registry = tmp_path / "registry"
    _write_snapshot(snapshot, end="2026-07-24T00:00:00Z", raw=raw)
    register_okx_one_hour_forward_snapshot(snapshot, registry, inst_id="BTC-USDT")
    journal = registry / "BTC-USDT" / "okx-1h-forward-registry.jsonl"
    journal.write_bytes(journal.read_bytes()[:-1])

    with pytest.raises(ValueError, match="truncated final record"):
        replay_okx_one_hour_forward_registry(registry, inst_id="BTC-USDT")


@pytest.mark.parametrize("retained_records", [0, 1])
def test_forward_registry_rejects_complete_record_truncation(
    tmp_path: Path,
    retained_records: int,
) -> None:
    raw = _fixture_response_bytes()
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    registry = tmp_path / "registry"
    _write_snapshot(previous, end="2026-07-24T00:00:00Z", raw=raw)
    _write_snapshot(current, end="2026-07-24T01:00:00Z", raw=raw)
    register_okx_one_hour_forward_snapshot(previous, registry, inst_id="BTC-USDT")
    register_okx_one_hour_forward_snapshot(current, registry, inst_id="BTC-USDT")

    journal = registry / "BTC-USDT" / "okx-1h-forward-registry.jsonl"
    lines = journal.read_bytes().splitlines(keepends=True)
    assert len(lines) == 2
    journal.write_bytes(b"".join(lines[:retained_records]))

    with pytest.raises(ValueError, match="unreferenced immutable snapshot evidence"):
        replay_okx_one_hour_forward_registry(registry, inst_id="BTC-USDT")


def test_forward_registry_rejects_tampered_stored_source_artifact(tmp_path: Path) -> None:
    raw = _fixture_response_bytes()
    snapshot = tmp_path / "snapshot"
    registry = tmp_path / "registry"
    _write_snapshot(snapshot, end="2026-07-24T00:00:00Z", raw=raw)
    record = register_okx_one_hour_forward_snapshot(
        snapshot,
        registry,
        inst_id="BTC-USDT",
    )
    stored_raw = (
        registry / "BTC-USDT" / "snapshots" / record["snapshot_id"] / "okx-BTC-USDT-1H.raw.json"
    )
    stored_raw.write_bytes(stored_raw.read_bytes() + b" ")

    with pytest.raises(ValueError, match="raw-pages hash mismatch"):
        replay_okx_one_hour_forward_registry(registry, inst_id="BTC-USDT")
