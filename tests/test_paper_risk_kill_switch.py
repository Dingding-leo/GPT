from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.paper_risk_kill_switch import (
    InstrumentExposure,
    PaperRiskKillSwitchPolicy,
    PaperRiskStateSnapshot,
    ProposedInstrumentExposure,
    evaluate_paper_risk_kill_switch,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"


def _real_okx_mark() -> tuple[datetime, float, str]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(rows_bytes).hexdigest() == _EXPECTED_FIXTURE_SHA256
    assert metadata["fixture_rows_sha256"] == _EXPECTED_FIXTURE_SHA256
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"

    rows = json.loads(rows_bytes)
    confirmed = next(row for row in rows if row[8] == "1")
    observed_at = datetime.fromtimestamp(int(confirmed[0]) / 1000, tz=UTC)
    return observed_at, float(confirmed[4]), _EXPECTED_FIXTURE_SHA256


def _state(
    *,
    current_fraction: float,
    peak_fraction: float = 1.02,
    daily_turnover: float = 0.25,
    state_age_seconds: float = 1.0,
    market_age_seconds: float = 2.0,
    exposures: tuple[InstrumentExposure, ...] | None = None,
) -> tuple[PaperRiskStateSnapshot, datetime]:
    market_observed_at, real_mark, source_hash = _real_okx_mark()
    session_start_equity = real_mark * 0.2
    evaluated_at = market_observed_at + timedelta(seconds=market_age_seconds)
    observed_at = evaluated_at - timedelta(seconds=state_age_seconds)
    state_payload = {
        "current_fraction": current_fraction,
        "daily_turnover": daily_turnover,
        "evaluated_at": evaluated_at.isoformat(),
        "peak_fraction": peak_fraction,
        "real_mark": real_mark,
    }
    state_hash = hashlib.sha256(
        json.dumps(state_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    instrument_exposures = (
        (InstrumentExposure("BTC-USDT", 0.50),) if exposures is None else exposures
    )
    return (
        PaperRiskStateSnapshot(
            observed_at_utc=observed_at,
            session_start_utc=min(market_observed_at, observed_at),
            market_data_observed_at_utc=market_observed_at,
            session_start_equity=session_start_equity,
            peak_equity=session_start_equity * peak_fraction,
            current_equity=session_start_equity * current_fraction,
            daily_underlying_turnover=daily_turnover,
            instrument_exposures=instrument_exposures,
            portfolio_state_sha256=state_hash,
            market_data_source_sha256=source_hash,
        ),
        evaluated_at,
    )


def _policy() -> PaperRiskKillSwitchPolicy:
    return PaperRiskKillSwitchPolicy(
        daily_loss_trigger_fraction=0.05,
        drawdown_trigger_fraction=0.10,
        daily_underlying_turnover_trigger=1.0,
        maximum_state_age_seconds=5.0,
        maximum_market_data_age_seconds=5.0,
    )


def test_daily_loss_switch_blocks_increase_but_allows_sell_only_reduction() -> None:
    snapshot, evaluated_at = _state(current_fraction=0.94)

    blocked = evaluate_paper_risk_kill_switch(
        (ProposedInstrumentExposure("BTC-USDT", 0.60),),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )
    assert blocked.mode == "reduce_only"
    assert blocked.active_triggers == ("daily_loss_limit",)
    assert blocked.allowed is False
    assert blocked.blockers == ("kill_switch_exposure_increase:BTC-USDT",)
    with pytest.raises(RuntimeError, match="BTC-USDT"):
        blocked.assert_allowed()

    reduction = evaluate_paper_risk_kill_switch(
        (ProposedInstrumentExposure("BTC-USDT", 0.20),),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )
    assert reduction.mode == "reduce_only"
    assert reduction.active_triggers == ("daily_loss_limit",)
    assert reduction.allowed is True
    assert reduction.blockers == ()
    reduction.assert_allowed()


def test_stale_market_data_and_abnormal_turnover_force_reduce_only() -> None:
    snapshot, evaluated_at = _state(
        current_fraction=1.0,
        daily_turnover=1.25,
        state_age_seconds=2.0,
        market_age_seconds=12.0,
    )
    decision = evaluate_paper_risk_kill_switch(
        (ProposedInstrumentExposure("BTC-USDT", 0.55),),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )

    assert decision.active_triggers == (
        "stale_market_data",
        "abnormal_turnover_limit",
    )
    assert decision.market_data_age_seconds == 12.0
    assert decision.daily_underlying_turnover == 1.25
    assert decision.allowed is False


def test_stale_portfolio_state_is_evaluated_with_fresh_market_data() -> None:
    snapshot, evaluated_at = _state(
        current_fraction=1.0,
        state_age_seconds=12.0,
        market_age_seconds=2.0,
    )

    blocked = evaluate_paper_risk_kill_switch(
        (ProposedInstrumentExposure("BTC-USDT", 0.55),),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )
    assert blocked.active_triggers == ("stale_portfolio_state",)
    assert blocked.state_age_seconds == 12.0
    assert blocked.market_data_age_seconds == 2.0
    assert blocked.mode == "reduce_only"
    assert blocked.allowed is False

    reduction = evaluate_paper_risk_kill_switch(
        (ProposedInstrumentExposure("BTC-USDT", 0.20),),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )
    assert reduction.active_triggers == ("stale_portfolio_state",)
    assert reduction.allowed is True


def test_instrument_increase_cannot_hide_behind_lower_portfolio_exposure() -> None:
    snapshot, evaluated_at = _state(
        current_fraction=0.94,
        exposures=(
            InstrumentExposure("BTC-USDT", 0.60),
            InstrumentExposure("ETH-USDT", 0.10),
        ),
    )
    decision = evaluate_paper_risk_kill_switch(
        (
            ProposedInstrumentExposure("ETH-USDT", 0.20),
            ProposedInstrumentExposure("BTC-USDT", 0.20),
        ),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )

    assert decision.current_gross_exposure == pytest.approx(0.70)
    assert decision.proposed_gross_exposure == pytest.approx(0.40)
    assert decision.exposure_increase_instruments == ("ETH-USDT",)
    assert decision.allowed is False


def test_snapshot_exposures_remain_in_gross_exposure_when_proposal_is_partial() -> None:
    snapshot, evaluated_at = _state(
        current_fraction=0.94,
        exposures=(
            InstrumentExposure("BTC-USDT", 0.60),
            InstrumentExposure("ETH-USDT", 0.20),
        ),
    )
    decision = evaluate_paper_risk_kill_switch(
        (ProposedInstrumentExposure("BTC-USDT", 0.10),),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )

    assert decision.mode == "reduce_only"
    assert decision.allowed is True
    assert decision.current_gross_exposure == pytest.approx(0.80)
    assert decision.proposed_gross_exposure == pytest.approx(0.30)
    assert [change.instrument_id for change in decision.exposure_changes] == [
        "BTC-USDT",
        "ETH-USDT",
    ]
    assert decision.exposure_changes[1].proposed_exposure == pytest.approx(0.20)


def test_healthy_state_allows_normal_exposure_change_and_is_order_independent() -> None:
    snapshot, evaluated_at = _state(
        current_fraction=1.0,
        exposures=(
            InstrumentExposure("BTC-USDT", 0.30),
            InstrumentExposure("ETH-USDT", 0.10),
        ),
    )
    first = evaluate_paper_risk_kill_switch(
        (
            ProposedInstrumentExposure("ETH-USDT", 0.20),
            ProposedInstrumentExposure("BTC-USDT", 0.40),
        ),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )
    second = evaluate_paper_risk_kill_switch(
        (
            ProposedInstrumentExposure("BTC-USDT", 0.40),
            ProposedInstrumentExposure("ETH-USDT", 0.20),
        ),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )

    assert first.mode == "normal"
    assert first.active_triggers == ()
    assert first.allowed is True
    assert first.decision_id == second.decision_id
    assert first == second


def test_evaluation_rejects_future_market_data_and_state_rejects_inconsistent_peak() -> None:
    market_observed_at, real_mark, source_hash = _real_okx_mark()
    state_hash = hashlib.sha256(b"paper-state").hexdigest()

    future_market_snapshot = PaperRiskStateSnapshot(
        observed_at_utc=market_observed_at,
        session_start_utc=market_observed_at,
        market_data_observed_at_utc=market_observed_at + timedelta(microseconds=1),
        session_start_equity=real_mark,
        peak_equity=real_mark,
        current_equity=real_mark,
        daily_underlying_turnover=0.0,
        instrument_exposures=(InstrumentExposure("BTC-USDT", 0.25),),
        portfolio_state_sha256=state_hash,
        market_data_source_sha256=source_hash,
    )
    with pytest.raises(ValueError, match="market data"):
        evaluate_paper_risk_kill_switch(
            (ProposedInstrumentExposure("BTC-USDT", 0.25),),
            snapshot=future_market_snapshot,
            policy=_policy(),
            evaluated_at_utc=market_observed_at,
        )

    with pytest.raises(ValueError, match="peak_equity"):
        PaperRiskStateSnapshot(
            observed_at_utc=market_observed_at,
            session_start_utc=market_observed_at,
            market_data_observed_at_utc=market_observed_at,
            session_start_equity=real_mark,
            peak_equity=real_mark * 0.99,
            current_equity=real_mark,
            daily_underlying_turnover=0.0,
            instrument_exposures=(InstrumentExposure("BTC-USDT", 0.25),),
            portfolio_state_sha256=state_hash,
            market_data_source_sha256=source_hash,
        )
