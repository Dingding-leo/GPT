from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import ExecutionQuoteBinding, bind_execution_quote
from gpt_quant.paper_execution_attempt import (
    PaperExecutionAttempt,
    record_paper_execution_attempt,
)

_REAL_OKX_RESPONSE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_INSTRUMENT_SHA256 = "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _intent() -> TargetPositionIntent:
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-five-bps",
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


def _binding():
    return bind_execution_quote(
        _intent(),
        _quote(),
        decision_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=250,
    )


def test_attempt_binds_submission_fill_price_and_measured_latency() -> None:
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

    replayed = PaperExecutionAttempt.from_json_bytes(attempt.to_json_bytes())
    assert replayed == attempt
    assert replayed.binding_id == binding.binding_id
    assert replayed.target_intent_id == intent.intent_id
    assert replayed.quote_snapshot_id == quote.snapshot_id
    assert replayed.reference_bid_price == quote.bid_price
    assert replayed.reference_ask_price == quote.ask_price
    assert replayed.fill_price_convention == "market-vwap-at-touch-or-worse"
    assert replayed.decision_to_submission_latency_us == 50_000
    assert replayed.quote_observed_to_submission_latency_us == 150_000
    assert replayed.quote_received_to_submission_latency_us == 100_000
    assert replayed.submission_to_outcome_latency_us == 50_000
    replayed.assert_reconstructs(intent, binding, quote)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        (
            {"submitted_at_utc": datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC)},
            "strictly after the decision",
        ),
        (
            {"outcome_at_utc": datetime(2026, 7, 21, 0, 0, 0, 449_999, tzinfo=UTC)},
            "strictly after submission",
        ),
        (
            {"average_fill_price": "66113.8"},
            "cannot improve through the reference ask",
        ),
        (
            {
                "outcome": "rejected",
                "filled_base_quantity": "0.01",
                "average_fill_price": "66114",
            },
            "rejected attempts cannot contain fills",
        ),
        (
            {
                "outcome": "partial",
                "filled_base_quantity": "0.1",
                "average_fill_price": "66114",
            },
            "positive incomplete fill",
        ),
        (
            {
                "submitted_at_utc": datetime(2026, 7, 21, 0, 0, 0, 550_001, tzinfo=UTC),
                "outcome_at_utc": datetime(2026, 7, 21, 0, 0, 0, 600_000, tzinfo=UTC),
            },
            "stale at paper submission",
        ),
    ],
)
def test_attempt_rejects_ambiguous_timing_price_and_quantity_states(
    overrides: dict[str, object],
    error: str,
) -> None:
    values: dict[str, object] = {
        "submitted_at_utc": datetime(2026, 7, 21, 0, 0, 0, 450_000, tzinfo=UTC),
        "outcome_at_utc": datetime(2026, 7, 21, 0, 0, 0, 500_000, tzinfo=UTC),
        "side": "buy",
        "requested_base_quantity": "0.1",
        "outcome": "filled",
        "filled_base_quantity": "0.1",
        "average_fill_price": "66114",
        "reason_code": "paper-touch-fill",
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=error):
        record_paper_execution_attempt(_intent(), _binding(), _quote(), **values)


def test_attempt_rejects_forged_binding_before_creating_execution_evidence() -> None:
    intent = _intent()
    quote = _quote()
    binding = _binding()
    forged = ExecutionQuoteBinding(
        target_intent_id="0" * 64,
        quote_snapshot_id=binding.quote_snapshot_id,
        instrument_id=binding.instrument_id,
        decision_at_utc=binding.decision_at_utc,
        maximum_age_ms=binding.maximum_age_ms,
        quote_observed_at_utc=binding.quote_observed_at_utc,
        quote_received_at_utc=binding.quote_received_at_utc,
        instrument_snapshot_sha256=binding.instrument_snapshot_sha256,
        observed_spread_bps=binding.observed_spread_bps,
    )

    with pytest.raises(ValueError, match="target intent does not match"):
        record_paper_execution_attempt(
            intent,
            forged,
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


def test_attempt_rejects_sell_fill_above_bid_and_tampered_latency() -> None:
    intent = _intent()
    quote = _quote()
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=250,
    )

    with pytest.raises(ValueError, match="cannot improve through the reference bid"):
        record_paper_execution_attempt(
            intent,
            binding,
            quote,
            submitted_at_utc=datetime(2026, 7, 21, 0, 0, 0, 450_000, tzinfo=UTC),
            outcome_at_utc=datetime(2026, 7, 21, 0, 0, 0, 500_000, tzinfo=UTC),
            side="sell",
            requested_base_quantity="0.1",
            outcome="filled",
            filled_base_quantity="0.1",
            average_fill_price=quote.ask_price,
            reason_code="paper-touch-fill",
        )

    attempt = record_paper_execution_attempt(
        intent,
        binding,
        quote,
        submitted_at_utc=datetime(2026, 7, 21, 0, 0, 0, 450_000, tzinfo=UTC),
        outcome_at_utc=datetime(2026, 7, 21, 0, 0, 0, 500_000, tzinfo=UTC),
        side="sell",
        requested_base_quantity="0.1",
        outcome="partial",
        filled_base_quantity="0.04",
        average_fill_price=quote.bid_price,
        reason_code="paper-partial-touch-fill",
    )
    payload = json.loads(attempt.to_json_bytes())
    payload["decision_to_submission_latency_us"] += 1
    tampered = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode() + b"\n"
    with pytest.raises(ValueError, match="does not match the recorded timestamps"):
        PaperExecutionAttempt.from_json_bytes(tampered)
