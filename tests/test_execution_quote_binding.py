from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from decimal import localcontext

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import ExecutionQuoteBinding, bind_execution_quote

_REAL_OKX_RESPONSE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_INSTRUMENT_SHA256 = "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _intent() -> TargetPositionIntent:
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-five-bps",
        strategy_revision="7a3b3d349af5522cbcfb813fbcd669abbd9df1fe",
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


def test_binding_is_canonical_and_reconstructs_exact_quote_and_intent() -> None:
    intent = _intent()
    quote = _quote()
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=250,
    )

    replayed = ExecutionQuoteBinding.from_json_bytes(binding.to_json_bytes())
    assert replayed == binding
    assert replayed.target_intent_id == intent.intent_id
    assert replayed.quote_snapshot_id == quote.snapshot_id
    assert replayed.instrument_snapshot_sha256 == quote.instrument_snapshot_sha256
    assert replayed.observed_spread_bps == (
        "0.030250824713108741127054976336292368170687253361245"
    )
    replayed.assert_reconstructs(intent, quote)


def test_timezone_equivalent_inputs_produce_identical_binding_identity() -> None:
    intent = _intent()
    quote = _quote()
    utc_binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=250,
    )
    adelaide = timezone(timedelta(hours=9, minutes=30))
    offset_binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 21, 9, 30, 0, 400_000, tzinfo=adelaide),
        maximum_age_ms=250,
    )

    assert offset_binding.to_json_bytes() == utc_binding.to_json_bytes()
    assert offset_binding.binding_id == utc_binding.binding_id


def test_binding_rejects_tampering_and_mixed_quote_evidence() -> None:
    intent = _intent()
    quote = _quote()
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=250,
    )
    payload = json.loads(binding.to_json_bytes())
    payload["observed_spread_bps"] = "999"
    tampered = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() + b"\n"

    with pytest.raises(ValueError, match="ID does not match"):
        ExecutionQuoteBinding.from_json_bytes(tampered)

    other_quote = ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=quote.observed_at_utc,
        received_at_utc=quote.received_at_utc,
        bid_price="66113.7",
        bid_quantity=quote.bid_quantity,
        ask_price=quote.ask_price,
        ask_quantity=quote.ask_quantity,
        source_response_sha256="0" * 64,
        instrument_snapshot_sha256=quote.instrument_snapshot_sha256,
    )
    with pytest.raises(ValueError, match="does not match its quote evidence"):
        binding.assert_reconstructs(intent, other_quote)


def test_binding_preserves_strict_post_receipt_and_staleness_rules() -> None:
    intent = _intent()
    quote = _quote()

    with pytest.raises(ValueError, match="received before the decision"):
        bind_execution_quote(
            intent,
            quote,
            decision_at_utc=quote.received_at_utc,
            maximum_age_ms=250,
        )

    with pytest.raises(ValueError, match="stale"):
        bind_execution_quote(
            intent,
            quote,
            decision_at_utc=datetime(2026, 7, 21, 0, 0, 1, tzinfo=UTC),
            maximum_age_ms=250,
        )


def test_direct_binding_and_canonical_replay_reject_stale_quote_evidence() -> None:
    quote = _quote()
    values = {
        "target_intent_id": _intent().intent_id,
        "quote_snapshot_id": quote.snapshot_id,
        "instrument_id": quote.instrument_id,
        "decision_at_utc": datetime(2026, 7, 21, 0, 0, 1, tzinfo=UTC),
        "maximum_age_ms": 250,
        "quote_observed_at_utc": quote.observed_at_utc,
        "quote_received_at_utc": quote.received_at_utc,
        "instrument_snapshot_sha256": quote.instrument_snapshot_sha256,
        "observed_spread_bps": "0.030250824713108741127054976336292368170687253361245",
    }

    with pytest.raises(ValueError, match="stale"):
        ExecutionQuoteBinding(**values)

    stale_payload = {"schema_version": 1, **values, "binding_id": "0" * 64}
    stale_payload.update(
        {
            "decision_at_utc": "2026-07-21T00:00:01.000000Z",
            "quote_observed_at_utc": "2026-07-21T00:00:00.300000Z",
            "quote_received_at_utc": "2026-07-21T00:00:00.350000Z",
        }
    )
    serialized = json.dumps(stale_payload, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    with pytest.raises(ValueError, match="stale"):
        ExecutionQuoteBinding.from_json_bytes(serialized)


def test_binding_identity_and_reconstruction_ignore_decimal_context() -> None:
    intent = _intent()
    quote = _quote()
    decision_at = datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC)

    with localcontext() as context:
        context.prec = 10
        low_precision = bind_execution_quote(
            intent,
            quote,
            decision_at_utc=decision_at,
            maximum_age_ms=250,
        )
    with localcontext() as context:
        context.prec = 50
        high_precision = bind_execution_quote(
            intent,
            quote,
            decision_at_utc=decision_at,
            maximum_age_ms=250,
        )

    assert low_precision.to_json_bytes() == high_precision.to_json_bytes()
    assert low_precision.binding_id == high_precision.binding_id
    assert low_precision.observed_spread_bps == (
        "0.030250824713108741127054976336292368170687253361245"
    )

    with localcontext() as context:
        context.prec = 6
        low_precision.assert_reconstructs(intent, quote)
