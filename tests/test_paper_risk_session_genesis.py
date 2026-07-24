from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant.paper_risk_kill_switch import (
    InstrumentExposure,
    PaperRiskKillSwitchPolicy,
    PaperRiskStateSnapshot,
)
from gpt_quant.paper_risk_session_gate import (
    advance_paper_risk_session_high_watermarks,
)

_FIXTURE_DIR = (
    Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1h-raw-20260724"
)
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_ROWS_SHA256 = (
    "228828e32a5a43f0010a326ab65c368dbdc6202a158738b0e9956ad7c6393137"
)


def _real_okx_1h_anchor() -> tuple[datetime, datetime, float]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(rows_bytes).hexdigest() == _EXPECTED_ROWS_SHA256
    assert metadata["fixture_rows_sha256"] == _EXPECTED_ROWS_SHA256
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1H"
    assert metadata["confirm_values"] == ["1"]

    rows = json.loads(rows_bytes)
    timestamps = sorted(
        datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC) for row in rows
    )
    close_by_timestamp = {
        datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC): float(row[4])
        for row in rows
    }
    return timestamps[0], timestamps[1], close_by_timestamp[timestamps[0]]


def _snapshot(
    *,
    observed_at: datetime,
    session_start: datetime,
    equity: float,
) -> PaperRiskStateSnapshot:
    return PaperRiskStateSnapshot(
        observed_at_utc=observed_at,
        session_start_utc=session_start,
        market_data_observed_at_utc=observed_at,
        session_start_equity=equity,
        peak_equity=equity,
        current_equity=equity,
        daily_underlying_turnover=0.0,
        instrument_exposures=(InstrumentExposure("BTC-USDT", 0.25),),
        portfolio_state_sha256=hashlib.sha256(
            observed_at.isoformat().encode()
        ).hexdigest(),
        market_data_source_sha256=_EXPECTED_ROWS_SHA256,
    )


def test_mid_session_restart_cannot_create_a_fresh_zeroed_latch() -> None:
    session_start, next_hour, real_mark = _real_okx_1h_anchor()
    equity = real_mark * 0.10
    policy = PaperRiskKillSwitchPolicy(
        daily_loss_trigger_fraction=0.05,
        drawdown_trigger_fraction=0.10,
        daily_underlying_turnover_trigger=1.0,
        maximum_state_age_seconds=7_200.0,
        maximum_market_data_age_seconds=7_200.0,
    )

    exact_start = _snapshot(
        observed_at=session_start,
        session_start=session_start,
        equity=equity,
    )
    genesis = advance_paper_risk_session_high_watermarks(exact_start, policy=policy)
    assert genesis.previous_high_watermark_id is None
    assert genesis.observed_at_utc == genesis.session_start_utc

    recovered_restart = _snapshot(
        observed_at=next_hour,
        session_start=session_start,
        equity=equity,
    )
    assert recovered_restart.daily_loss_fraction == 0.0
    assert recovered_restart.drawdown_fraction == 0.0
    assert recovered_restart.daily_underlying_turnover == 0.0

    with pytest.raises(ValueError, match="require a session-start snapshot"):
        advance_paper_risk_session_high_watermarks(recovered_restart, policy=policy)
