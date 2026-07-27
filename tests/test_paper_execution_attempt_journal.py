from __future__ import annotations

import hashlib
import inspect
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.execution_quote_binding_journal import (
    ExecutionQuoteBindingJournal,
    record_execution_quote_binding,
)
from gpt_quant.execution_quote_evidence import record_execution_quote_evidence
from gpt_quant.paper_execution_attempt import record_paper_execution_attempt
from gpt_quant.paper_execution_attempt_journal import (
    load_paper_execution_attempt_journal,
    record_paper_execution_attempt_evidence,
)
from gpt_quant.target_intent_journal import record_target_position_intent

_REAL_OKX_BOOK_BYTES = (
    b'{"code":"0","data":[{"asks":[["41006.8","0.60038921","0","1"]],'
    b'"bids":[["41006.3","0.30178218","0","2"]],"seqId":3235851742,'
    b'"ts":"1629966436396"}],"msg":""}\n'
)
_REAL_OKX_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_REAL_OKX_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_REAL_OKX_INSTRUMENT_BYTES = (
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
_REAL_OKX_CANDLE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _intent() -> TargetPositionIntent:
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-five-bps",
        strategy_revision="49a4eefa9e6d349237832d75f9c1c96070c6799c",
        source_data_sha256=_REAL_OKX_CANDLE_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2021, 8, 25, tzinfo=UTC),
        signal_bar_close_utc=datetime(2021, 8, 26, 8, 27, 16, 300_000, tzinfo=UTC),
        decision_not_before_utc=datetime(2021, 8, 26, 8, 27, 16, 396_000, tzinfo=UTC),
        expires_at_utc=datetime(2021, 8, 27, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def _quote() -> ExecutionQuoteSnapshot:
    payload = json.loads(_REAL_OKX_BOOK_BYTES)
    book = payload["data"][0]
    observed = datetime.fromtimestamp(int(book["ts"]) / 1000, tz=UTC)
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=observed,
        received_at_utc=observed + timedelta(milliseconds=50),
        bid_price=book["bids"][0][0],
        bid_quantity=book["bids"][0][1],
        ask_price=book["asks"][0][0],
        ask_quantity=book["asks"][0][1],
        source_response_sha256=hashlib.sha256(_REAL_OKX_BOOK_BYTES).hexdigest(),
        instrument_snapshot_sha256=hashlib.sha256(_REAL_OKX_INSTRUMENT_BYTES).hexdigest(),
    )


def _record_quote(path: Path, quote: ExecutionQuoteSnapshot):
    parameters = inspect.signature(record_execution_quote_evidence).parameters
    if "source_response_bytes" in parameters:
        return record_execution_quote_evidence(
            path,
            quote,
            source_response_bytes=_REAL_OKX_BOOK_BYTES,
            instrument_snapshot_bytes=_REAL_OKX_INSTRUMENT_BYTES,
        )
    return record_execution_quote_evidence(path, quote)


def _sources(tmp_path: Path):
    assert hashlib.sha256(_REAL_OKX_BOOK_BYTES).hexdigest() == _REAL_OKX_BOOK_SHA256
    assert hashlib.sha256(_REAL_OKX_INSTRUMENT_BYTES).hexdigest() == _REAL_OKX_INSTRUMENT_SHA256
    intent = _intent()
    quote = _quote()
    intent_journal = record_target_position_intent(tmp_path / "intents.jsonl", intent)
    quote_store = _record_quote(tmp_path / "quotes", quote)
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=quote.received_at_utc + timedelta(milliseconds=50),
        maximum_age_ms=250,
    )
    binding_journal = record_execution_quote_binding(
        tmp_path / "bindings.jsonl",
        binding,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )
    return intent_journal, quote_store, binding, binding_journal


def _attempt(
    binding,
    quote_store,
    *,
    submitted_offset_ms: int,
    outcome: str,
    requested: str = "0.1",
):
    quote = quote_store.snapshots[0]
    submitted = binding.decision_at_utc + timedelta(milliseconds=submitted_offset_ms)
    filled = requested if outcome == "filled" else "0"
    fill_price = quote.ask_price if outcome == "filled" else "0"
    return record_paper_execution_attempt(
        binding,
        quote,
        submitted_at_utc=submitted,
        outcome_at_utc=submitted + timedelta(milliseconds=50),
        side="buy",
        requested_base_quantity=requested,
        outcome=outcome,
        filled_base_quantity=filled,
        average_fill_price=fill_price,
        reason_code="paper-touch-fill" if outcome == "filled" else "paper-accepted",
    )


def test_attempt_journal_replays_exact_chain_with_deterministic_root(tmp_path: Path) -> None:
    intent_journal, quote_store, binding, binding_journal = _sources(tmp_path)
    earlier = _attempt(
        binding,
        quote_store,
        submitted_offset_ms=25,
        outcome="accepted",
        requested="0.05",
    )
    later = _attempt(
        binding,
        quote_store,
        submitted_offset_ms=50,
        outcome="filled",
        requested="0.1",
    )
    path = tmp_path / "paper-state" / "attempts.jsonl"

    first = record_paper_execution_attempt_evidence(
        path,
        later,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    complete = record_paper_execution_attempt_evidence(
        path,
        earlier,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    repeated = record_paper_execution_attempt_evidence(
        path,
        earlier,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    replayed = load_paper_execution_attempt_journal(
        path,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )

    expected = (earlier, later)
    expected_bytes = b"".join(attempt.to_json_bytes() for attempt in expected)
    assert first.attempts == (later,)
    assert complete == repeated == replayed
    assert replayed.attempts == expected
    assert replayed.sha256 == hashlib.sha256(expected_bytes).hexdigest()
    assert replayed.to_bytes() == expected_bytes
    assert path.parent.stat().st_mode & 0o022 == 0
    assert path.stat().st_mode & 0o777 == 0o600


def test_attempt_journal_rejects_conflicting_outcome_and_missing_binding(tmp_path: Path) -> None:
    intent_journal, quote_store, binding, binding_journal = _sources(tmp_path)
    accepted = _attempt(binding, quote_store, submitted_offset_ms=50, outcome="accepted")
    filled = _attempt(binding, quote_store, submitted_offset_ms=50, outcome="filled")
    path = tmp_path / "paper-state" / "attempts.jsonl"
    record_paper_execution_attempt_evidence(
        path,
        accepted,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )

    with pytest.raises(ValueError, match="conflicting outcomes for one submission"):
        record_paper_execution_attempt_evidence(
            path,
            filled,
            intent_journal=intent_journal,
            quote_store=quote_store,
            binding_journal=binding_journal,
        )

    missing = ExecutionQuoteBindingJournal(
        bindings=(),
        sha256=hashlib.sha256(b"").hexdigest(),
    )
    with pytest.raises(ValueError, match="missing execution binding"):
        load_paper_execution_attempt_journal(
            path,
            intent_journal=intent_journal,
            quote_store=quote_store,
            binding_journal=missing,
        )


def test_attempt_journal_recovers_crash_stage_and_rejects_tampering(tmp_path: Path) -> None:
    intent_journal, quote_store, binding, binding_journal = _sources(tmp_path)
    attempt = _attempt(binding, quote_store, submitted_offset_ms=50, outcome="filled")
    path = tmp_path / "paper-state" / "attempts.jsonl"
    expected = record_paper_execution_attempt_evidence(
        path,
        attempt,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )

    stage = path.parent / ".paper-execution-attempt-journal-123-deadbeefdeadbeef.tmp"
    stage.write_bytes(b"unpublished paper outcome")
    os.chmod(stage, 0o600)
    replayed = record_paper_execution_attempt_evidence(
        path,
        attempt,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    assert replayed == expected
    assert not stage.exists()

    payload = json.loads(path.read_bytes())
    payload["reason_code"] = "tampered"
    path.write_bytes(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() + b"\n")
    path.chmod(0o600)
    with pytest.raises(ValueError, match="ID does not match"):
        load_paper_execution_attempt_journal(
            path,
            intent_journal=intent_journal,
            quote_store=quote_store,
            binding_journal=binding_journal,
        )
