from __future__ import annotations

from datetime import UTC, datetime

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.paper_execution_attempt import record_paper_execution_attempt

_REAL_OKX_RESPONSE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_INSTRUMENT_SHA256 = "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"


def _intent() -> TargetPositionIntent:
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-five-bps",
        strategy_revision="49a4eefa9e6d349237832d75f9c1c96070c6799c",
        source_data_sha256=_SOURCE_DATA_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2026, 7, 20, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 21, tzinfo=UTC),
        decision_not_before_utc=datetime(2026, 7, 21, 0, 0, 0, 200_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 21, 0, 0, 0, 500_000, tzinfo=UTC),
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


def test_paper_submission_rejects_expired_target_intent() -> None:
    intent = _intent()
    quote = _quote()
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        maximum_age_ms=250,
    )

    with pytest.raises(ValueError, match="target-position intent has expired"):
        record_paper_execution_attempt(
            intent,
            binding,
            quote,
            submitted_at_utc=intent.expires_at_utc,
            outcome_at_utc=datetime(2026, 7, 21, 0, 0, 0, 550_000, tzinfo=UTC),
            side="buy",
            requested_base_quantity="0.1",
            outcome="filled",
            filled_base_quantity="0.1",
            average_fill_price=quote.ask_price,
            reason_code="paper-touch-fill",
        )


def test_outcome_after_expiry_replays_when_submission_was_active() -> None:
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
        submitted_at_utc=datetime(2026, 7, 21, 0, 0, 0, 499_999, tzinfo=UTC),
        outcome_at_utc=datetime(2026, 7, 21, 0, 0, 0, 550_000, tzinfo=UTC),
        side="buy",
        requested_base_quantity="0.1",
        outcome="filled",
        filled_base_quantity="0.1",
        average_fill_price=quote.ask_price,
        reason_code="paper-touch-fill",
    )

    attempt.assert_reconstructs(intent, binding, quote)
