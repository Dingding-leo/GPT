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
    PaperRiskSessionHighWatermarks,
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


def _recovered_snapshot() -> tuple[PaperRiskStateSnapshot, datetime]:
    market_observed_at, real_mark, source_hash = _real_okx_anchor()
    evaluated_at = market_observed_at + timedelta(seconds=2)
    session_start_equity = real_mark * 0.2
    state_hash = hashlib.sha256(b"recovered-paper-state").hexdigest()
    return (
        PaperRiskStateSnapshot(
            observed_at_utc=evaluated_at - timedelta(seconds=1),
            session_start_utc=market_observed_at,
            market_data_observed_at_utc=market_observed_at,
            session_start_equity=session_start_equity,
            peak_equity=session_start_equity * 1.02,
            current_equity=session_start_equity,
            daily_underlying_turnover=0.25,
            instrument_exposures=(InstrumentExposure("BTC-USDT", 0.50),),
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


def test_recovered_equity_cannot_clear_session_loss_and_drawdown_stops() -> None:
    snapshot, evaluated_at = _recovered_snapshot()
    high_watermarks = PaperRiskSessionHighWatermarks(
        portfolio_state_sha256=snapshot.portfolio_state_sha256,
        maximum_daily_loss_fraction=0.06,
        maximum_drawdown_fraction=0.12,
    )

    blocked = evaluate_paper_risk_session_gate(
        (ProposedInstrumentExposure("BTC-USDT", 0.60),),
        snapshot=snapshot,
        policy=_policy(),
        high_watermarks=high_watermarks,
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
        snapshot=snapshot,
        policy=_policy(),
        high_watermarks=high_watermarks,
        evaluated_at_utc=evaluated_at,
    )
    assert reduction.active_triggers == ("daily_loss_limit", "drawdown_limit")
    assert reduction.allowed is True


def test_high_watermarks_fail_closed_on_state_hash_or_metric_regression() -> None:
    snapshot, evaluated_at = _recovered_snapshot()
    proposal = (ProposedInstrumentExposure("BTC-USDT", 0.20),)

    with pytest.raises(ValueError, match="source hash"):
        evaluate_paper_risk_session_gate(
            proposal,
            snapshot=snapshot,
            policy=_policy(),
            high_watermarks=PaperRiskSessionHighWatermarks(
                portfolio_state_sha256=hashlib.sha256(b"wrong-state").hexdigest(),
                maximum_daily_loss_fraction=0.06,
                maximum_drawdown_fraction=0.12,
            ),
            evaluated_at_utc=evaluated_at,
        )

    loss_snapshot = PaperRiskStateSnapshot(
        observed_at_utc=snapshot.observed_at_utc,
        session_start_utc=snapshot.session_start_utc,
        market_data_observed_at_utc=snapshot.market_data_observed_at_utc,
        session_start_equity=snapshot.session_start_equity,
        peak_equity=snapshot.peak_equity,
        current_equity=snapshot.session_start_equity * 0.90,
        daily_underlying_turnover=snapshot.daily_underlying_turnover,
        instrument_exposures=snapshot.instrument_exposures,
        portfolio_state_sha256=snapshot.portfolio_state_sha256,
        market_data_source_sha256=snapshot.market_data_source_sha256,
    )
    with pytest.raises(ValueError, match="maximum_daily_loss_fraction"):
        evaluate_paper_risk_session_gate(
            proposal,
            snapshot=loss_snapshot,
            policy=_policy(),
            high_watermarks=PaperRiskSessionHighWatermarks(
                portfolio_state_sha256=loss_snapshot.portfolio_state_sha256,
                maximum_daily_loss_fraction=0.09,
                maximum_drawdown_fraction=0.20,
            ),
            evaluated_at_utc=evaluated_at,
        )
