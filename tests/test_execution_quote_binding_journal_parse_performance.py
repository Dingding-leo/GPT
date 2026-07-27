from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

import gpt_quant.execution_quote_binding_journal as journal_module
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import ExecutionQuoteBinding, bind_execution_quote

_SOURCE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_QUOTE_SHA256 = "7d12a351f8f51320d1c8beee0063557e1c90388d66ac63412bf66ca544aeb3e3"
_INSTRUMENT_SHA256 = "290bd86ecbb1683351993197b0ec18001dfb604b9ba1cb864d9d6d327855f0eb"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _bindings(*, count: int = 4) -> tuple[ExecutionQuoteBinding, ...]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    result = []
    for index in range(count):
        signal_open = start + timedelta(hours=index)
        signal_close = signal_open + timedelta(hours=1)
        decision_not_before = signal_close + timedelta(milliseconds=100)
        intent = TargetPositionIntent(
            instrument_id="BTC-USDT",
            bar="1H",
            strategy_id="binding-parse-regression",
            strategy_revision="390d98361ccd62b58c18c3999cbcc62287208fdf",
            source_data_sha256=_SOURCE_SHA256,
            config_sha256=_CONFIG_SHA256,
            signal_bar_open_utc=signal_open,
            signal_bar_close_utc=signal_close,
            decision_not_before_utc=decision_not_before,
            expires_at_utc=decision_not_before + timedelta(minutes=1),
            target_position=(index % 10) / 10,
            minimum_position=0.0,
            maximum_position=1.0,
        )
        observed_at = decision_not_before + timedelta(milliseconds=5)
        quote = ExecutionQuoteSnapshot(
            provider="okx",
            instrument_id="BTC-USDT",
            observed_at_utc=observed_at,
            received_at_utc=observed_at + timedelta(milliseconds=5),
            bid_price="41006.3",
            bid_quantity="0.30178218",
            ask_price="41006.8",
            ask_quantity="0.60038921",
            source_response_sha256=_QUOTE_SHA256,
            instrument_snapshot_sha256=_INSTRUMENT_SHA256,
        )
        result.append(
            bind_execution_quote(
                intent,
                quote,
                decision_at_utc=quote.received_at_utc + timedelta(milliseconds=5),
                maximum_age_ms=250,
            )
        )
    return tuple(result)


def test_binding_journal_parse_serializes_each_record_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bindings = _bindings()
    payload = b"".join(binding.to_json_bytes() for binding in bindings)
    calls = 0
    original = ExecutionQuoteBinding.to_json_bytes

    def counted(self: ExecutionQuoteBinding) -> bytes:
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(ExecutionQuoteBinding, "to_json_bytes", counted)
    parsed = journal_module._parse_journal_bytes(payload)

    assert calls == len(bindings)
    assert parsed.bindings == bindings
    assert parsed.sha256 == hashlib.sha256(payload).hexdigest()
    assert parsed.to_bytes() == payload


def test_binding_journal_parse_still_rejects_out_of_order_records() -> None:
    bindings = _bindings()
    payload = b"".join(binding.to_json_bytes() for binding in reversed(bindings))

    with pytest.raises(ValueError, match="canonical chronological ordering"):
        journal_module._parse_journal_bytes(payload)
