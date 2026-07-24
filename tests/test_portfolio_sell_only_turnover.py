from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
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


def test_sell_only_de_risking_bypasses_batch_turnover_but_preserves_costs() -> None:
    equity, mark_at, fixture_sha256 = _real_confirmed_btc_mark()
    snapshot = PaperPortfolioRiskSnapshot(
        observed_at_utc="2026-07-20T00:00:05Z",
        equity=equity,
        cash=0.0,
        positions=(
            PortfolioPosition(
                instrument_id="BTC-USDT",
                quantity=1.0,
                mark_price=equity,
                mark_observed_at_utc=mark_at,
                mark_source_sha256=fixture_sha256,
            ),
        ),
    )
    policy = PortfolioTargetRiskPolicy(
        instrument_limits=(InstrumentTargetRiskLimit("BTC-USDT", 1.0, equity),),
        maximum_gross_target_exposure=1.0,
        maximum_gross_notional=equity,
        maximum_batch_turnover=0.2,
        minimum_cash_reserve=10_000.0,
        maximum_position_mark_age_seconds=10.0,
        costs=ExecutionCostInputs(
            spread_bps=1.0,
            slippage_bps=2.0,
            market_impact_bps=3.0,
            latency_bps=4.0,
        ),
    )
    intent = TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-5bps-walk-forward",
        strategy_revision=_STRATEGY_REVISION,
        source_data_sha256=fixture_sha256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc="2026-07-19T00:00:00Z",
        signal_bar_close_utc="2026-07-20T00:00:00Z",
        decision_not_before_utc="2026-07-20T00:00:03Z",
        expires_at_utc="2026-07-21T00:00:00Z",
        target_position=0.0,
        minimum_position=0.0,
        maximum_position=1.0,
    )

    decision = evaluate_target_position_intents((intent,), snapshot=snapshot, policy=policy)

    assert decision.allowed is True
    assert decision.blockers == ()
    assert decision.batch_turnover == pytest.approx(1.0)
    assert decision.required_buy_notional == 0.0
    assert decision.required_sell_notional == pytest.approx(equity)
    assert decision.required_cash == 0.0
    assert decision.exchange_fee_reserve == pytest.approx(equity * 5.0 / 10_000.0)
    assert decision.spread_reserve == pytest.approx(equity * 1.0 / 10_000.0)
    assert decision.slippage_reserve == pytest.approx(equity * 2.0 / 10_000.0)
    assert decision.market_impact_reserve == pytest.approx(equity * 3.0 / 10_000.0)
    assert decision.latency_reserve == pytest.approx(equity * 4.0 / 10_000.0)
    assert decision.stress_7_5_bps_reserve == pytest.approx(equity * 7.5 / 10_000.0)
    assert decision.stress_10_bps_reserve == pytest.approx(equity * 10.0 / 10_000.0)
    assert decision.stress_15_bps_reserve == pytest.approx(equity * 15.0 / 10_000.0)
