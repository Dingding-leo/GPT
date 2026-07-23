from __future__ import annotations

import hashlib
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_evidence import (
    load_execution_quote_evidence_store,
    record_execution_quote_evidence,
)

_REAL_OKX_FIXTURE_ROWS_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_RAW_PAGES_SHA256 = "0db4334a5fd7cdee0dc500b01cd5610b30d9b78f392b537f18c35ce1fd80971a"


def _quote(*, offset_ms: int, instrument_id: str = "BTC-USDT") -> ExecutionQuoteSnapshot:
    observed = datetime(2026, 7, 22, 0, 0, 0, 200_000, tzinfo=UTC) + timedelta(
        milliseconds=offset_ms
    )
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id=instrument_id,
        observed_at_utc=observed,
        received_at_utc=observed + timedelta(milliseconds=50),
        bid_price="66113.7",
        bid_quantity="0.5",
        ask_price="66113.9",
        ask_quantity="0.4",
        source_response_sha256=_REAL_OKX_RAW_PAGES_SHA256,
        instrument_snapshot_sha256=_REAL_OKX_FIXTURE_ROWS_SHA256,
    )


def test_execution_quote_store_replays_one_deterministic_root(tmp_path: Path) -> None:
    store_path = tmp_path / "quotes"
    later = _quote(offset_ms=100)
    earlier = _quote(offset_ms=0)

    first = record_execution_quote_evidence(store_path, later)
    complete = record_execution_quote_evidence(store_path, earlier)
    repeated = record_execution_quote_evidence(store_path, earlier)
    replayed = load_execution_quote_evidence_store(store_path)

    expected = (earlier, later)
    expected_payload = b"".join(snapshot.to_json_bytes() for snapshot in expected)
    assert first.snapshots == (later,)
    assert complete.snapshots == expected
    assert complete.sha256 == hashlib.sha256(expected_payload).hexdigest()
    assert repeated == complete
    assert replayed == complete
    assert replayed.to_bytes() == expected_payload
    assert store_path.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in store_path.glob("*.json"))
    assert not any(path.name.startswith(".execution-quote-") for path in store_path.iterdir())


def test_execution_quote_store_fsyncs_new_directory_and_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fsynced: list[tuple[int, int, int]] = []
    real_fsync = os.fsync

    def traced_fsync(descriptor: int) -> None:
        descriptor_stat = os.fstat(descriptor)
        fsynced.append(
            (descriptor_stat.st_dev, descriptor_stat.st_ino, stat.S_IFMT(descriptor_stat.st_mode))
        )
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", traced_fsync)
    store_path = tmp_path / "quotes"
    snapshot = _quote(offset_ms=0)
    record_execution_quote_evidence(store_path, snapshot)

    parent_stat = tmp_path.stat()
    store_stat = store_path.stat()
    snapshot_stat = (store_path / f"{snapshot.snapshot_id}.json").stat()
    identities = {(device, inode) for device, inode, _ in fsynced}
    assert (parent_stat.st_dev, parent_stat.st_ino) in identities
    assert (store_stat.st_dev, store_stat.st_ino) in identities
    assert (snapshot_stat.st_dev, snapshot_stat.st_ino) in identities


def test_execution_quote_store_rejects_tampered_or_unowned_names(tmp_path: Path) -> None:
    store_path = tmp_path / "quotes"
    snapshot = _quote(offset_ms=0)
    record_execution_quote_evidence(store_path, snapshot)
    snapshot_path = store_path / f"{snapshot.snapshot_id}.json"

    replacement = _quote(offset_ms=1)
    snapshot_path.write_bytes(replacement.to_json_bytes())
    os.chmod(snapshot_path, 0o600)
    with pytest.raises(ValueError, match="filename does not match"):
        load_execution_quote_evidence_store(store_path)

    snapshot_path.unlink()
    unexpected = store_path / "latest.json"
    unexpected.write_bytes(snapshot.to_json_bytes())
    os.chmod(unexpected, 0o600)
    with pytest.raises(ValueError, match="unexpected entry"):
        load_execution_quote_evidence_store(store_path)


def test_execution_quote_store_rejects_writable_directory_and_files(tmp_path: Path) -> None:
    store_path = tmp_path / "quotes"
    snapshot = _quote(offset_ms=0)
    record_execution_quote_evidence(store_path, snapshot)
    snapshot_path = store_path / f"{snapshot.snapshot_id}.json"

    os.chmod(snapshot_path, 0o640)
    with pytest.raises(ValueError, match="mode 0600"):
        load_execution_quote_evidence_store(store_path)

    os.chmod(snapshot_path, 0o600)
    os.chmod(store_path, 0o770)
    with pytest.raises(ValueError, match="mode 0700"):
        load_execution_quote_evidence_store(store_path)
