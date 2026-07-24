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
)
from gpt_quant.paper_risk_session_gate import (
    advance_paper_risk_session_high_watermarks,
    evaluate_paper_risk_session_gate,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"


def _real_okx_anchor() -> tuple[datetime, float, str]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(rows_bytes).hexdigest() == _EXPECTED_FIXTURE_SHA256
    assert metadata["fixture_rows_sha256"] == _EXPECTED_FIXTURE_SHA256
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"

    rows = json.loads(rows_bytes)
    confirmed = next(row for row in rows if row[8] == "1")
    return (
        datetime.fromtimestamp(int(confirmed[0]) / 1000, tz=UTC),
        float(confirmed[4]),
        _EXPECTED_FIXTURE_SHA256,
    )


def _snapshot(
    *,
    observed_at: datetime,
    session_start: datetime,
    session_start_equity: float,
    peak_equity: float,
    current_equity: float,
    state_name: str,
) -> PaperRiskStateSnapshot:
    return PaperRiskStateSnapshot(
        observed_at_utc=observed_at,
        session_start_utc=session_start,
        market_data_observed_at_utc=observed_at - timedelta(seconds=1),
        session_start_equity=session_start_equity,
        peak_equity=peak_equity,
        current_equity=current_equity,
        daily_underlying_turnover=0.25,
        instrument_exposures=(InstrumentExposure("BTC-USDT", 0.50),),
        portfolio_state_sha256=hashlib.sha256(state_name.encode()).hexdigest(),
        market_data_source_sha256=_EXPECTED_FIXTURE_SHA256,
    )


def _session_path() -> tuple[
    PaperRiskStateSnapshot,
    PaperRiskStateSnapshot,
    PaperRiskStateSnapshot,
    datetime,
]:
    market_observed_at, real_mark, _ = _real_okx_anchor()
    session_start_equity = real_mark * 0.2
    initial = _snapshot(
        observed_at=market_observed_at,
        session_start=market_observed_at,
        session_start_equity=session_start_equity,
        peak_equity=session_start_equity,
        current_equity=session_start_equity,
        state_name="paper-state-initial",
    )
    breached = _snapshot(
        observed_at=market_observed_at + timedelta(seconds=1),
        session_start=market_observed_at,
        session_start_equity=session_start_equity,
        peak_equity=session_start_equity,
        current_equity=session_start_equity * 0.88,
        state_name="paper-state-breached",
    )
    recovered = _snapshot(
        observed_at=market_observed_at + timedelta(seconds=2),
        session_start=market_observed_at,
        session_start_equity=session_start_equity,
        peak_equity=session_start_equity * 1.02,
        current_equity=session_start_equity,
        state_name="paper-state-recovered",
    )
    return initial, breached, recovered, market_observed_at + timedelta(seconds=3)


def _policy() -> PaperRiskKillSwitchPolicy:
    return PaperRiskKillSwitchPolicy(
        daily_loss_trigger_fraction=0.05,
        drawdown_trigger_fraction=0.10,
        daily_underlying_turnover_trigger=1.0,
        maximum_state_age_seconds=5.0,
        maximum_market_data_age_seconds=5.0,
    )


def test_recovered_equity_cannot_clear_append_only_session_stops() -> None:
    initial, breached, recovered, evaluated_at = _session_path()
    initial_watermarks = advance_paper_risk_session_high_watermarks(initial)
    breached_watermarks = advance_paper_risk_session_high_watermarks(
        breached,
        previous=initial_watermarks,
    )
    recovered_watermarks = advance_paper_risk_session_high_watermarks(
        recovered,
        previous=breached_watermarks,
    )

    assert initial_watermarks.previous_high_watermark_id is None
    assert breached_watermarks.previous_high_watermark_id == initial_watermarks.high_watermark_id
    assert recovered_watermarks.previous_high_watermark_id == breached_watermarks.high_watermark_id
    assert recovered_watermarks.maximum_daily_loss_fraction == pytest.approx(0.12)
    assert recovered_watermarks.maximum_drawdown_fraction == pytest.approx(0.12)

    blocked = evaluate_paper_risk_session_gate(
        (ProposedInstrumentExposure("BTC-USDT", 0.60),),
        snapshot=recovered,
        policy=_policy(),
        high_watermarks=recovered_watermarks,
        evaluated_at_utc=evaluated_at,
    )

    assert blocked.base_decision.daily_loss_fraction == 0.0
    assert blocked.base_decision.drawdown_fraction == pytest.approx(1 - 1 / 1.02)
    assert blocked.base_decision.mode == "normal"
    assert blocked.active_triggers == ("daily_loss_limit", "drawdown_limit")
    assert blocked.mode == "reduce_only"
    assert blocked.allowed is False
    assert blocked.blockers == ("kill_switch_exposure_increase:BTC-USDT",)

    reduction = evaluate_paper_risk_session_gate(
        (ProposedInstrumentExposure("BTC-USDT", 0.20),),
        snapshot=recovered,
        policy=_policy(),
        high_watermarks=recovered_watermarks,
        evaluated_at_utc=evaluated_at,
    )
    assert reduction.active_triggers == ("daily_loss_limit", "drawdown_limit")
    assert reduction.allowed is True


def test_session_watermark_transition_fails_closed_on_restart_and_ordering() -> None:
    initial, breached, recovered, evaluated_at = _session_path()
    initial_watermarks = advance_paper_risk_session_high_watermarks(initial)
    breached_watermarks = advance_paper_risk_session_high_watermarks(
        breached,
        previous=initial_watermarks,
    )

    with pytest.raises(ValueError, match="zero-loss, zero-drawdown"):
        advance_paper_risk_session_high_watermarks(recovered)

    with pytest.raises(ValueError, match="exact portfolio snapshot"):
        evaluate_paper_risk_session_gate(
            (ProposedInstrumentExposure("BTC-USDT", 0.20),),
            snapshot=recovered,
            policy=_policy(),
            high_watermarks=breached_watermarks,
            evaluated_at_utc=evaluated_at,
        )

    with pytest.raises(ValueError, match="older snapshot"):
        advance_paper_risk_session_high_watermarks(
            initial,
            previous=breached_watermarks,
        )

    replayed = advance_paper_risk_session_high_watermarks(
        breached,
        previous=breached_watermarks,
    )
    assert replayed is breached_watermarks
