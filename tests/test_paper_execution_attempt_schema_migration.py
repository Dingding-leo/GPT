from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.paper_execution_attempt import (
    PaperExecutionAttempt,
    record_paper_execution_attempt,
)

_REAL_OKX_RESPONSE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_INSTRUMENT_SHA256 = "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _intent(*, strategy_id: str = "canonical-five-bps") -> TargetPositionIntent:
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id=strategy_id,
        strategy_revision="a2b3e61a0591121346a6d29f1ddd3ad805aba68d",
        source_data_sha256=_SOURCE_DATA_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2026, 7, 20, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 21, tzinfo=UTC),
        decision_not_before_utc=datetime(2026, 7, 21, 0, 0, 0, 200_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 22, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def _quote() -> ExecutionQuoteSnapshot:
    return ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=datetime(2026, 7, 21, 0, 0, 0, 300_000, tzinfo=UTC),
        received_at_utc=datetime(2026, 7, 21, 0, 0, 0, 350_000, tzinfo=UTC),
        bid_price="66113.8",
        bid_quantity="0.42",
        ask_price="66114",
        ask_quantity="0.37",
        source_response_sha256=_REAL_OKX_RESPONSE_SHA256,
        instrument_snapshot_sha256=_REAL_OKX_INSTRUMENT_SHA256,
    )


def _attempt():
    intent = _intent()
    quote = _quote()
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=250,
    )
    attempt = record_paper_execution_attempt(
        intent,
        binding,
        quote,
        submitted_at_utc=datetime(2026, 7, 21, 0, 0, 0, 450_000, tzinfo=UTC),
        outcome_at_utc=datetime(2026, 7, 21, 0, 0, 0, 500_000, tzinfo=UTC),
        side="buy",
        requested_base_quantity="0.1",
        outcome="filled",
        filled_base_quantity="0.1",
        average_fill_price=quote.ask_price,
        reason_code="paper-touch-fill",
    )
    return intent, binding, quote, attempt


def _legacy_v1_bytes(attempt: PaperExecutionAttempt) -> bytes:
    payload = attempt.to_dict()
    payload.pop("target_intent_id")
    payload["schema_version"] = 1
    payload_without_id = {key: value for key, value in payload.items() if key != "attempt_id"}
    canonical_payload = json.dumps(
        payload_without_id,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    payload["attempt_id"] = hashlib.sha256(canonical_payload).hexdigest()
    return (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
        + b"\n"
    )


def test_schema_v1_requires_explicit_evidence_bound_migration() -> None:
    intent, binding, quote, attempt = _attempt()
    legacy = _legacy_v1_bytes(attempt)

    assert attempt.schema_version == 2
    with pytest.raises(ValueError, match="schema 1 requires explicit evidence-bound migration"):
        PaperExecutionAttempt.from_json_bytes(legacy)

    migrated = PaperExecutionAttempt.migrate_v1_json_bytes(legacy, intent, binding, quote)
    assert migrated == attempt
    assert migrated.target_intent_id == intent.intent_id
    migrated.assert_reconstructs(intent, binding, quote)


def test_schema_v1_migration_rejects_wrong_target_lineage() -> None:
    _, binding, quote, attempt = _attempt()

    with pytest.raises(ValueError, match="target intent does not match"):
        PaperExecutionAttempt.migrate_v1_json_bytes(
            _legacy_v1_bytes(attempt),
            _intent(strategy_id="different-strategy"),
            binding,
            quote,
        )
