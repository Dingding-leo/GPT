from __future__ import annotations

from datetime import UTC, datetime

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.execution_quote import ExecutionQuoteSnapshot
from gpt_quant.paper_order_decision import PaperOrderDecision
from gpt_quant.paper_post_only_order_intent import build_paper_post_only_order_intent

# Official public OKX BTC-USDT depth-one values and response hashes pinned by the
# repository's execution-quote regressions. Equality at target activation is the
# only boundary condition varied here.
_REAL_OKX_RESPONSE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"
_REAL_OKX_INSTRUMENT_SHA256 = "fa567055978b3974e728664af9e90f52dbedf1ee6864a1cdd4cb6f6a462de521"
_SOURCE_DATA_SHA256 = "429abcbe5deb56ad6c7e1790cea101644a9fedd622f40de64eec5fd1ac3c4187"
_CONFIG_SHA256 = "6b06037376bce5df483311704f7b701c5e03a2a2735b2dd3361036fccd94da1a"
_ACTIVATION = datetime(2026, 7, 21, 0, 0, 0, 300_000, tzinfo=UTC)


def test_post_only_order_intent_accepts_quote_observed_at_target_activation() -> None:
    target = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1H",
        strategy_id="canonical-one-hour-five-bps",
        strategy_revision="e5e7ef22a23e6673c0183f47c0398f6af490d6d1",
        source_data_sha256=_SOURCE_DATA_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=datetime(2026, 7, 20, 23, tzinfo=UTC),
        signal_bar_close_utc=datetime(2026, 7, 21, tzinfo=UTC),
        decision_not_before_utc=_ACTIVATION,
        expires_at_utc=datetime(2026, 7, 21, 1, tzinfo=UTC),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    quote = ExecutionQuoteSnapshot(
        provider="okx",
        instrument_id="BTC-USDT",
        observed_at_utc=_ACTIVATION,
        received_at_utc=datetime(2026, 7, 21, 0, 0, 0, 350_000, tzinfo=UTC),
        bid_price="66113.8",
        bid_quantity="0.42",
        ask_price="66114",
        ask_quantity="0.37",
        source_response_sha256=_REAL_OKX_RESPONSE_SHA256,
        instrument_snapshot_sha256=_REAL_OKX_INSTRUMENT_SHA256,
    )
    decision = PaperOrderDecision(
        target_intent_id=target.intent_id,
        instrument_id=target.instrument_id,
        decided_at_utc=datetime(2026, 7, 21, 0, 0, 0, 400_000, tzinfo=UTC),
        market_observed_at_utc=quote.observed_at_utc,
        outcome="planned",
        reason_code="pretrade_passed",
        order_type="post_only_limit",
        side="buy",
        base_quantity="0.001",
        instrument_snapshot_sha256=quote.instrument_snapshot_sha256,
        market_snapshot_sha256=quote.snapshot_id,
        portfolio_state_before_sha256="4" * 64,
        risk_state_before_sha256="5" * 64,
        exchange_fee_bps="5",
        spread_bps="0.030250824713108741127054976336292368170687253361245",
        slippage_bps="0",
        market_impact_bps="0",
        latency_ms=50,
    )

    intent = build_paper_post_only_order_intent(
        decision,
        target,
        quote,
        created_at_utc=datetime(2026, 7, 21, 0, 0, 0, 450_000, tzinfo=UTC),
        expires_at_utc=datetime(2026, 7, 21, 0, 0, 0, 500_000, tzinfo=UTC),
        maximum_quote_age_ms=250,
        limit_price=quote.bid_price,
    )

    assert intent.quote_observed_at_utc == target.decision_not_before_utc
    assert intent.exchange_fee_bps == "5"
