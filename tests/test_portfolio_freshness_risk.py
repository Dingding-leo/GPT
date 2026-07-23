from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.portfolio_freshness_risk import (
    PortfolioFreshnessPolicy,
    evaluate_fresh_target_position_intents,
)
from gpt_quant.portfolio_target_risk import (
    ExecutionCostInputs,
    InstrumentTargetRiskLimit,
    PaperPortfolioRiskSnapshot,
    PortfolioPosition,
    PortfolioTargetRiskPolicy,
    evaluate_target_position_intents,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_STRATEGY_REVISION = "3bd594692c2ac95ec364008c1a6a8a89df4aa1f5"


def _real_confirmed_btc_mark() -> tuple[float, datetime, str]:
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    rows_bytes = _ROWS_PATH.read_bytes()
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert hashlib.sha256(rows_bytes).hexdigest() == metadata["fixture_rows_sha256"]
    rows = json.loads(rows_bytes)
    confirmed = next(row for row in rows if row[8] == "1")
    observed_at = datetime.fromtimestamp(int(confirmed[0]) / 1000.0, tz=UTC)
    return float(confirmed[4]), observed_at, str(metadata["fixture_rows_sha256"])


def _intent(source_sha256: str, *, target_position: float = 0.5) -> TargetPositionIntent:
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-5bps-walk-forward",
        strategy_revision=_STRATEGY_REVISION,
        source_data_sha256=source_sha256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc="2026-07-19T00:00:00Z",
        signal_bar_close_utc="2026-07-20T00:00:00Z",
        decision_not_before_utc="2026-07-20T00:00:03Z",
        expires_at_utc="2026-07-21T00:00:00Z",
        target_position=target_position,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def _state(
    *, target_position: float = 0.5
) -> tuple[PaperPortfolioRiskSnapshot, PortfolioTargetRiskPolicy, TargetPositionIntent]:
    equity, mark_at, fixture_sha256 = _real_confirmed_btc_mark()
    position = PortfolioPosition(
        instrument_id="BTC-USDT",
        quantity=0.5,
        mark_price=equity,
        mark_observed_at_utc=mark_at,
        mark_source_sha256=fixture_sha256,
    )
    snapshot = PaperPortfolioRiskSnapshot(
        observed_at_utc="2026-07-20T00:00:05Z",
        equity=equity,
        cash=equity * 0.5,
        positions=(position,),
    )
    target_policy = PortfolioTargetRiskPolicy(
        instrument_limits=(InstrumentTargetRiskLimit("BTC-USDT", 1.0, equity),),
        maximum_gross_target_exposure=1.0,
        maximum_gross_notional=equity,
        maximum_batch_turnover=1.0,
        minimum_cash_reserve=0.0,
        maximum_position_mark_age_seconds=60.0,
        costs=ExecutionCostInputs(
            spread_bps=1.0,
            slippage_bps=2.0,
            market_impact_bps=3.0,
            latency_bps=4.0,
        ),
    )
    return snapshot, target_policy, _intent(fixture_sha256, target_position=target_position)


def test_freshness_gate_rejects_replayed_stale_portfolio_state() -> None:
    snapshot, target_policy, intent = _state()

    legacy_decision = evaluate_target_position_intents(
        (intent,),
        snapshot=snapshot,
        policy=target_policy,
    )
    assert legacy_decision.allowed is True
    assert legacy_decision.instrument_measures[0].current_mark_age_seconds == 5.0

    decision = evaluate_fresh_target_position_intents(
        (intent,),
        snapshot=snapshot,
        target_policy=target_policy,
        freshness_policy=PortfolioFreshnessPolicy(
            maximum_snapshot_age_seconds=10.0,
            maximum_mark_age_seconds=10.0,
        ),
        decision_at_utc="2026-07-20T00:00:20Z",
    )

    assert decision.allowed is False
    assert decision.portfolio_snapshot_age_seconds == 15.0
    assert decision.instrument_mark_ages[0].instrument_id == "BTC-USDT"
    assert decision.instrument_mark_ages[0].age_seconds == 20.0
    assert decision.blockers == (
        "stale_portfolio_snapshot",
        "stale_position_mark:BTC-USDT",
    )
    with pytest.raises(RuntimeError, match="stale_portfolio_snapshot"):
        decision.assert_allowed()


def test_freshness_gate_preserves_target_limits_and_separate_cost_attribution() -> None:
    snapshot, target_policy, intent = _state(target_position=0.6)
    decision = evaluate_fresh_target_position_intents(
        (intent,),
        snapshot=snapshot,
        target_policy=target_policy,
        freshness_policy=PortfolioFreshnessPolicy(
            maximum_snapshot_age_seconds=10.0,
            maximum_mark_age_seconds=10.0,
        ),
        decision_at_utc=snapshot.observed_at_utc,
    )

    target = decision.target_risk_decision
    traded_notional = snapshot.equity * 0.1
    assert decision.allowed is True
    assert decision.blockers == ()
    assert decision.portfolio_snapshot_age_seconds == 0.0
    assert decision.instrument_mark_ages[0].age_seconds == 5.0
    assert target.traded_notional == pytest.approx(traded_notional)
    assert target.exchange_fee_reserve == pytest.approx(traded_notional * 5.0 / 10_000.0)
    assert target.spread_reserve == pytest.approx(traded_notional * 1.0 / 10_000.0)
    assert target.slippage_reserve == pytest.approx(traded_notional * 2.0 / 10_000.0)
    assert target.market_impact_reserve == pytest.approx(traded_notional * 3.0 / 10_000.0)
    assert target.latency_reserve == pytest.approx(traded_notional * 4.0 / 10_000.0)
    assert target.stress_7_5_bps_reserve == pytest.approx(traded_notional * 7.5 / 10_000.0)
    assert target.stress_10_bps_reserve == pytest.approx(traded_notional * 10.0 / 10_000.0)
    assert target.stress_15_bps_reserve == pytest.approx(traded_notional * 15.0 / 10_000.0)
    decision.assert_allowed()


def test_freshness_gate_rejects_future_state_and_invalid_policy() -> None:
    snapshot, target_policy, intent = _state()

    with pytest.raises(ValueError, match="after the risk decision"):
        evaluate_fresh_target_position_intents(
            (intent,),
            snapshot=snapshot,
            target_policy=target_policy,
            freshness_policy=PortfolioFreshnessPolicy(
                maximum_snapshot_age_seconds=10.0,
                maximum_mark_age_seconds=10.0,
            ),
            decision_at_utc="2026-07-20T00:00:04Z",
        )

    for invalid in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError, match="positive finite"):
            PortfolioFreshnessPolicy(
                maximum_snapshot_age_seconds=invalid,
                maximum_mark_age_seconds=10.0,
            )
