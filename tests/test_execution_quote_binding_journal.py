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
from gpt_quant.execution_quote_binding_journal import (
    load_execution_quote_binding_journal,
    record_execution_quote_binding,
)
from gpt_quant.execution_quote_evidence import record_execution_quote_evidence
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


def _intent(*, target_position: float = 0.25) -> TargetPositionIntent:
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
        target_position=target_position,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def _quote(*, receipt_offset_ms: int = 50) -> ExecutionQuoteSnapshot:
    payload = json.loads(_REAL_OKX_BOOK_BYTES)
    book = payload["data"][0]
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime.fromtimestamp(int(book["ts"]) / 1000, tz=UTC),
        received_at_utc=datetime.fromtimestamp(int(book["ts"]) / 1000, tz=UTC)
        + timedelta(milliseconds=receipt_offset_ms),
        bid_price=book["bids"][0][0],
        bid_quantity=book["bids"][0][1],
        ask_price=book["asks"][0][0],
        ask_quantity=book["asks"][0][1],
        source_response_sha256=hashlib.sha256(_REAL_OKX_BOOK_BYTES).hexdigest(),
        instrument_snapshot_sha256=_REAL_OKX_INSTRUMENT_SHA256,
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


def _sources(tmp_path: Path, *, quote: ExecutionQuoteSnapshot | None = None):
    intent = _intent()
    quote = quote or _quote()
    intent_journal = record_target_position_intent(tmp_path / "intents.jsonl", intent)
    quote_store = _record_quote(tmp_path / "quotes", quote)
    return intent, quote, intent_journal, quote_store


def test_binding_journal_replays_from_exact_persisted_sources(tmp_path: Path) -> None:
    assert hashlib.sha256(_REAL_OKX_BOOK_BYTES).hexdigest() == _REAL_OKX_BOOK_SHA256
    assert hashlib.sha256(_REAL_OKX_INSTRUMENT_BYTES).hexdigest() == _REAL_OKX_INSTRUMENT_SHA256
    intent, quote, intent_journal, quote_store = _sources(tmp_path)
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=quote.received_at_utc + timedelta(milliseconds=50),
        maximum_age_ms=250,
    )
    path = tmp_path / "bindings.jsonl"

    recorded = record_execution_quote_binding(
        path,
        binding,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )
    repeated = record_execution_quote_binding(
        path,
        binding,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )
    replayed = load_execution_quote_binding_journal(
        path,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )

    assert recorded == repeated == replayed
    assert replayed.bindings == (binding,)
    assert replayed.sha256 == hashlib.sha256(binding.to_json_bytes()).hexdigest()
    replayed.bindings[0].assert_reconstructs(intent, quote)


def test_binding_journal_rejects_missing_or_mixed_quote_sources(tmp_path: Path) -> None:
    intent, quote, intent_journal, quote_store = _sources(tmp_path)
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=quote.received_at_utc + timedelta(milliseconds=50),
        maximum_age_ms=250,
    )
    path = tmp_path / "bindings.jsonl"
    record_execution_quote_binding(
        path,
        binding,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )

    other_quote = _quote(receipt_offset_ms=60)
    other_quote_store = _record_quote(tmp_path / "other-quotes", other_quote)
    with pytest.raises(ValueError, match="missing execution quote"):
        load_execution_quote_binding_journal(
            path,
            intent_journal=intent_journal,
            quote_store=other_quote_store,
        )

    combined_quote_store = _record_quote(tmp_path / "quotes", other_quote)
    other_binding = bind_execution_quote(
        intent,
        other_quote,
        decision_at_utc=binding.decision_at_utc,
        maximum_age_ms=250,
    )
    with pytest.raises(ValueError, match="conflicting quotes for one target decision"):
        record_execution_quote_binding(
            path,
            other_binding,
            intent_journal=intent_journal,
            quote_store=combined_quote_store,
        )


def test_binding_journal_rejects_noncanonical_or_tampered_replay(tmp_path: Path) -> None:
    intent, quote, intent_journal, quote_store = _sources(tmp_path)
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=quote.received_at_utc + timedelta(milliseconds=50),
        maximum_age_ms=250,
    )
    path = tmp_path / "bindings.jsonl"
    record_execution_quote_binding(
        path,
        binding,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )

    path.write_bytes(b"\n" + binding.to_json_bytes())
    path.chmod(0o600)
    with pytest.raises(ValueError, match="canonical newline-terminated"):
        load_execution_quote_binding_journal(
            path,
            intent_journal=intent_journal,
            quote_store=quote_store,
        )
