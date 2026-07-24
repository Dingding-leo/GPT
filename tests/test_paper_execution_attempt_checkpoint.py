from __future__ import annotations

import hashlib
import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.execution_quote_binding_journal import record_execution_quote_binding
from gpt_quant.execution_quote_evidence import record_execution_quote_evidence
from gpt_quant.paper_execution_attempt import record_paper_execution_attempt
from gpt_quant.paper_execution_attempt_checkpoint import (
    PaperExecutionAttemptCheckpoint,
    load_checkpointed_paper_execution_attempt_journal,
    record_checkpointed_paper_execution_attempt_evidence,
)
from gpt_quant.target_intent_journal import record_target_position_intent

_REAL_OKX_BOOK_BYTES = (
    b'{"code":"0","data":[{"asks":[["41006.8","0.60038921","0","1"]],'
    b'"bids":[["41006.3","0.30178218","0","2"]],"seqId":3235851742,'
    b'"ts":"1629966436396"}],"msg":""}\n'
)
_REAL_OKX_BOOK_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
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
_REAL_OKX_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"


def _sources(tmp_path: Path):
    assert hashlib.sha256(_REAL_OKX_BOOK_BYTES).hexdigest() == _REAL_OKX_BOOK_SHA256
    assert hashlib.sha256(_REAL_OKX_INSTRUMENT_BYTES).hexdigest() == _REAL_OKX_INSTRUMENT_SHA256
    intent = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-five-bps",
        strategy_revision="49a4eefa9e6d349237832d75f9c1c96070c6799c",
        source_data_sha256="dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481",
        config_sha256="6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a",
        signal_bar_open_utc=datetime(2021, 8, 25, tzinfo=UTC),
        signal_bar_close_utc=datetime(2021, 8, 26, 8, 27, 16, 300_000, tzinfo=UTC),
        decision_not_before_utc=datetime(2021, 8, 26, 8, 27, 16, 396_000, tzinfo=UTC),
        expires_at_utc=datetime(2021, 8, 27, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    payload = json.loads(_REAL_OKX_BOOK_BYTES)
    book = payload["data"][0]
    observed = datetime.fromtimestamp(int(book["ts"]) / 1000, tz=UTC)
    quote = ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=observed,
        received_at_utc=observed + timedelta(milliseconds=50),
        bid_price=book["bids"][0][0],
        bid_quantity=book["bids"][0][1],
        ask_price=book["asks"][0][0],
        ask_quantity=book["asks"][0][1],
        source_response_sha256=_REAL_OKX_BOOK_SHA256,
        instrument_snapshot_sha256=_REAL_OKX_INSTRUMENT_SHA256,
    )
    intent_journal = record_target_position_intent(tmp_path / "intents.jsonl", intent)
    parameters = inspect.signature(record_execution_quote_evidence).parameters
    if "source_response_bytes" in parameters:
        quote_store = record_execution_quote_evidence(
            tmp_path / "quotes",
            quote,
            source_response_bytes=_REAL_OKX_BOOK_BYTES,
            instrument_snapshot_bytes=_REAL_OKX_INSTRUMENT_BYTES,
        )
    else:
        quote_store = record_execution_quote_evidence(tmp_path / "quotes", quote)
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


def _attempt(binding, quote_store, *, offset_ms: int, outcome: str, requested: str):
    quote = quote_store.snapshots[0]
    submitted = binding.decision_at_utc + timedelta(milliseconds=offset_ms)
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


def test_checkpoint_rejects_valid_older_complete_record_prefix(tmp_path: Path) -> None:
    intent_journal, quote_store, binding, binding_journal = _sources(tmp_path)
    path = tmp_path / "paper-state" / "attempts.jsonl"
    first = _attempt(binding, quote_store, offset_ms=25, outcome="accepted", requested="0.05")
    second = _attempt(binding, quote_store, offset_ms=50, outcome="filled", requested="0.1")

    first_journal, first_checkpoint = record_checkpointed_paper_execution_attempt_evidence(
        path,
        first,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    second_journal, second_checkpoint = record_checkpointed_paper_execution_attempt_evidence(
        path,
        second,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    assert first_checkpoint.sequence == 1
    assert second_checkpoint.sequence == 2
    assert second_checkpoint.previous_checkpoint_id == first_checkpoint.checkpoint_id

    path.write_bytes(first_journal.to_bytes())
    with pytest.raises(ValueError, match="does not match its durable checkpoint"):
        load_checkpointed_paper_execution_attempt_journal(
            path,
            intent_journal=intent_journal,
            quote_store=quote_store,
            binding_journal=binding_journal,
        )

    path.write_bytes(second_journal.to_bytes())
    replayed, checkpoint = load_checkpointed_paper_execution_attempt_journal(
        path,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    assert replayed == second_journal
    assert checkpoint == second_checkpoint


def test_journal_advance_without_checkpoint_blocks_startup(tmp_path: Path) -> None:
    intent_journal, quote_store, binding, binding_journal = _sources(tmp_path)
    path = tmp_path / "paper-state" / "attempts.jsonl"
    first = _attempt(binding, quote_store, offset_ms=25, outcome="accepted", requested="0.05")
    second = _attempt(binding, quote_store, offset_ms=50, outcome="filled", requested="0.1")

    record_checkpointed_paper_execution_attempt_evidence(
        path,
        first,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    from gpt_quant.paper_execution_attempt_journal import record_paper_execution_attempt_evidence

    record_paper_execution_attempt_evidence(
        path,
        second,
        intent_journal=intent_journal,
        quote_store=quote_store,
        binding_journal=binding_journal,
    )
    with pytest.raises(ValueError, match="does not match its durable checkpoint"):
        load_checkpointed_paper_execution_attempt_journal(
            path,
            intent_journal=intent_journal,
            quote_store=quote_store,
            binding_journal=binding_journal,
        )


def test_checkpoint_parser_rejects_duplicate_fields() -> None:
    payload = (
        b'{"attempt_count":1,"attempt_count":1,"checkpoint_id":"'
        + b"0" * 64
        + b'","journal_sha256":"'
        + b"0" * 64
        + b'","previous_checkpoint_id":null,"schema_version":1,"sequence":1}\n'
    )
    with pytest.raises(ValueError, match="duplicate checkpoint field"):
        PaperExecutionAttemptCheckpoint.from_json_bytes(payload)
