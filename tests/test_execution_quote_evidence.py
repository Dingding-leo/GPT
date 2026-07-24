from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_evidence import (
    ExecutionQuoteEvidence,
    load_execution_quote_evidence_store,
    record_execution_quote_evidence,
)

_REAL_OKX_ORDER_BOOK_RESPONSE = (
    b'{"code":"0","data":[{"asks":[["41006.8","0.60038921","0","1"]],'
    b'"bids":[["41006.3","0.30178218","0","2"]],"seqId":3235851742,'
    b'"ts":"1629966436396"}],"msg":""}\n'
)
_REAL_OKX_INSTRUMENT_RESPONSE = (
    b'{"code":"0","data":[{"alias":"","baseCcy":"BTC","category":"1",'
    b'"contTdSwTime":"1704876947000","ctMult":"","ctType":"","ctVal":"",'
    b'"ctValCcy":"","expTime":"","groupId":"1","instFamily":"",'
    b'"instId":"BTC-USDT","instType":"SPOT","lever":"10",'
    b'"listTime":"1606468572000","lotSz":"0.00000001",'
    b'"maxIcebergSz":"9999999999.0000000000000000","maxLmtAmt":"1000000",'
    b'"maxLmtSz":"9999999999","maxMktAmt":"1000000","maxMktSz":"",'
    b'"maxStopSz":"","maxTriggerSz":"9999999999.0000000000000000",'
    b'"maxTwapSz":"9999999999.0000000000000000","minSz":"0.00001",'
    b'"optType":"","openType":"call_auction","preMktSwTime":"",'
    b'"quoteCcy":"USDT","settleCcy":"","state":"live","stk":"",'
    b'"tickSz":"0.1","uly":""}],"msg":""}\n'
)
_REAL_OKX_ORDER_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_REAL_OKX_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"


def _quote(*, offset_ms: int, instrument_id: str = "BTC-USDT") -> ExecutionQuoteSnapshot:
    observed = datetime(2026, 7, 22, 0, 0, 0, 200_000, tzinfo=UTC) + timedelta(
        milliseconds=offset_ms
    )
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id=instrument_id,
        observed_at_utc=observed,
        received_at_utc=observed + timedelta(milliseconds=50),
        bid_price="41006.3",
        bid_quantity="0.30178218",
        ask_price="41006.8",
        ask_quantity="0.60038921",
        source_response_sha256=_REAL_OKX_ORDER_BOOK_SHA256,
        instrument_snapshot_sha256=_REAL_OKX_INSTRUMENT_SHA256,
    )


def _record(store_path: Path, snapshot: ExecutionQuoteSnapshot):
    return record_execution_quote_evidence(
        store_path,
        snapshot,
        source_response_bytes=_REAL_OKX_ORDER_BOOK_RESPONSE,
        instrument_snapshot_bytes=_REAL_OKX_INSTRUMENT_RESPONSE,
    )


def test_execution_quote_store_replays_one_deterministic_root(tmp_path: Path) -> None:
    assert hashlib.sha256(_REAL_OKX_ORDER_BOOK_RESPONSE).hexdigest() == _REAL_OKX_ORDER_BOOK_SHA256
    assert hashlib.sha256(_REAL_OKX_INSTRUMENT_RESPONSE).hexdigest() == _REAL_OKX_INSTRUMENT_SHA256

    store_path = tmp_path / "quotes"
    later = _quote(offset_ms=100)
    earlier = _quote(offset_ms=0)

    first = _record(store_path, later)
    complete = _record(store_path, earlier)
    repeated = _record(store_path, earlier)
    replayed = load_execution_quote_evidence_store(store_path)

    expected_snapshots = (earlier, later)
    expected_payload = b"".join(record.to_json_bytes() for record in complete.records)
    independently_replayed = tuple(
        ExecutionQuoteEvidence.from_json_bytes(record.to_json_bytes())
        for record in complete.records
    )
    assert first.snapshots == (later,)
    assert complete.snapshots == expected_snapshots
    assert independently_replayed == complete.records
    assert complete.sha256 == hashlib.sha256(expected_payload).hexdigest()
    assert repeated == complete
    assert replayed == complete
    assert replayed.to_bytes() == expected_payload
    assert all(
        record.source_response_bytes == _REAL_OKX_ORDER_BOOK_RESPONSE for record in replayed.records
    )
    assert all(
        record.instrument_snapshot_bytes == _REAL_OKX_INSTRUMENT_RESPONSE
        for record in replayed.records
    )
    assert store_path.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in store_path.glob("*.json"))
    assert not any(path.name.startswith(".execution-quote-") for path in store_path.iterdir())


def test_execution_quote_store_recovers_stages_left_by_crashed_writer(tmp_path: Path) -> None:
    store_path = tmp_path / "quotes"
    snapshot = _quote(offset_ms=0)
    expected = _record(store_path, snapshot)
    destination = store_path / f"{snapshot.snapshot_id}.json"

    incomplete_stage = store_path / ".execution-quote-101-deadbeefdeadbeef.tmp"
    incomplete_stage.write_bytes(b"partial execution quote")
    os.chmod(incomplete_stage, 0o600)

    published_stage = store_path / ".execution-quote-202-feedfacefeedface.tmp"
    os.link(destination, published_stage)
    assert destination.stat().st_nlink == 2

    replayed = load_execution_quote_evidence_store(store_path)

    assert replayed == expected
    assert not incomplete_stage.exists()
    assert not published_stage.exists()
    assert destination.stat().st_nlink == 1


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
    _record(store_path, snapshot)

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
    _record(store_path, snapshot)
    snapshot_path = store_path / f"{snapshot.snapshot_id}.json"

    replacement = ExecutionQuoteEvidence(
        snapshot=_quote(offset_ms=1),
        source_response_bytes=_REAL_OKX_ORDER_BOOK_RESPONSE,
        instrument_snapshot_bytes=_REAL_OKX_INSTRUMENT_RESPONSE,
    )
    snapshot_path.write_bytes(replacement.to_json_bytes())
    os.chmod(snapshot_path, 0o600)
    with pytest.raises(ValueError, match="filename does not match"):
        load_execution_quote_evidence_store(store_path)

    snapshot_path.unlink()
    unexpected = store_path / "latest.json"
    unexpected.write_bytes(replacement.to_json_bytes())
    os.chmod(unexpected, 0o600)
    with pytest.raises(ValueError, match="unexpected entry"):
        load_execution_quote_evidence_store(store_path)


def test_execution_quote_store_rejects_missing_or_tampered_source_artifacts(tmp_path: Path) -> None:
    snapshot = _quote(offset_ms=0)
    with pytest.raises(ValueError, match="source response bytes"):
        record_execution_quote_evidence(
            tmp_path / "missing-source",
            snapshot,
            source_response_bytes=b"{}\n",
            instrument_snapshot_bytes=_REAL_OKX_INSTRUMENT_RESPONSE,
        )

    store_path = tmp_path / "quotes"
    _record(store_path, snapshot)
    snapshot_path = store_path / f"{snapshot.snapshot_id}.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    payload["source_response_base64"] = "e30K"
    snapshot_path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.chmod(snapshot_path, 0o600)
    with pytest.raises(ValueError, match="source response bytes"):
        load_execution_quote_evidence_store(store_path)


def test_execution_quote_store_rejects_writable_directory_and_files(tmp_path: Path) -> None:
    store_path = tmp_path / "quotes"
    snapshot = _quote(offset_ms=0)
    _record(store_path, snapshot)
    snapshot_path = store_path / f"{snapshot.snapshot_id}.json"

    os.chmod(snapshot_path, 0o640)
    with pytest.raises(ValueError, match="mode 0600"):
        load_execution_quote_evidence_store(store_path)

    os.chmod(snapshot_path, 0o600)
    os.chmod(store_path, 0o770)
    with pytest.raises(ValueError, match="mode 0700"):
        load_execution_quote_evidence_store(store_path)
