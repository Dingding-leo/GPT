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
    PaperRiskSessionLatch,
    advance_paper_risk_session_latch,
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
    current_fraction: float,
    observed_offset_seconds: float,
    state_name: str,
    session_start_utc: datetime | None = None,
) -> tuple[PaperRiskStateSnapshot, datetime]:
    market_observed_at, real_mark, source_hash = _real_okx_anchor()
    session_start = market_observed_at if session_start_utc is None else session_start_utc
    observed_at = market_observed_at + timedelta(seconds=observed_offset_seconds)
    evaluated_at = observed_at + timedelta(seconds=1)
    session_start_equity = real_mark * 0.2
    state_hash = hashlib.sha256(state_name.encode("utf-8")).hexdigest()
    return (
        PaperRiskStateSnapshot(
            observed_at_utc=observed_at,
            session_start_utc=session_start,
            market_data_observed_at_utc=observed_at - timedelta(milliseconds=100),
            session_start_equity=session_start_equity,
            peak_equity=session_start_equity * 1.02,
            current_equity=session_start_equity * current_fraction,
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


def test_recovered_equity_cannot_clear_latched_session_stops_after_replay() -> None:
    breached, _ = _snapshot(
        current_fraction=0.90,
        observed_offset_seconds=1.0,
        state_name="breached-paper-state",
    )
    breached_latch = advance_paper_risk_session_latch(breached)
    assert breached_latch.maximum_daily_loss_fraction == pytest.approx(0.10)
    assert breached_latch.maximum_drawdown_fraction > 0.10

    recovered, evaluated_at = _snapshot(
        current_fraction=1.0,
        observed_offset_seconds=2.0,
        state_name="recovered-paper-state",
        session_start_utc=breached.session_start_utc,
    )
    recovered_latch = advance_paper_risk_session_latch(
        recovered,
        previous_latch=breached_latch,
    )
    replayed_latch = PaperRiskSessionLatch.from_json_bytes(recovered_latch.to_json_bytes())

    blocked = evaluate_paper_risk_session_gate(
        (ProposedInstrumentExposure("BTC-USDT", 0.60),),
        snapshot=recovered,
        policy=_policy(),
        session_latch=replayed_latch,
        evaluated_at_utc=evaluated_at,
    )

    assert blocked.base_decision.mode == "normal"
    assert blocked.base_decision.daily_loss_fraction == 0.0
    assert blocked.active_triggers == ("daily_loss_limit", "drawdown_limit")
    assert blocked.mode == "reduce_only"
    assert blocked.allowed is False
    assert blocked.blockers == ("kill_switch_exposure_increase:BTC-USDT",)
    assert recovered_latch.previous_latch_id == breached_latch.latch_id

    reduction = evaluate_paper_risk_session_gate(
        (ProposedInstrumentExposure("BTC-USDT", 0.20),),
        snapshot=recovered,
        policy=_policy(),
        session_latch=replayed_latch,
        evaluated_at_utc=evaluated_at,
    )
    assert reduction.active_triggers == ("daily_loss_limit", "drawdown_limit")
    assert reduction.allowed is True


def test_session_latch_advance_is_idempotent_and_rejects_stale_or_cross_session_state() -> None:
    first, _ = _snapshot(
        current_fraction=0.94,
        observed_offset_seconds=1.0,
        state_name="first-paper-state",
    )
    first_latch = advance_paper_risk_session_latch(first)
    assert advance_paper_risk_session_latch(first, previous_latch=first_latch) == first_latch

    second, evaluated_at = _snapshot(
        current_fraction=1.0,
        observed_offset_seconds=2.0,
        state_name="second-paper-state",
        session_start_utc=first.session_start_utc,
    )
    second_latch = advance_paper_risk_session_latch(second, previous_latch=first_latch)

    with pytest.raises(ValueError, match="not advanced"):
        evaluate_paper_risk_session_gate(
            (ProposedInstrumentExposure("BTC-USDT", 0.20),),
            snapshot=second,
            policy=_policy(),
            session_latch=first_latch,
            evaluated_at_utc=evaluated_at,
        )

    with pytest.raises(ValueError, match="strictly"):
        advance_paper_risk_session_latch(first, previous_latch=second_latch)

    new_session, _ = _snapshot(
        current_fraction=1.0,
        observed_offset_seconds=3.0,
        state_name="new-session-state",
        session_start_utc=first.session_start_utc + timedelta(seconds=3),
    )
    with pytest.raises(ValueError, match="session_start_utc"):
        advance_paper_risk_session_latch(new_session, previous_latch=second_latch)


def test_session_latch_replay_rejects_duplicate_fields_and_tampering() -> None:
    snapshot, _ = _snapshot(
        current_fraction=0.90,
        observed_offset_seconds=1.0,
        state_name="tamper-paper-state",
    )
    latch = advance_paper_risk_session_latch(snapshot)
    raw = latch.to_json_bytes()

    duplicate = raw.replace(
        b'"schema_version":1',
        b'"schema_version":1,"schema_version":1',
        1,
    )
    with pytest.raises(ValueError, match="duplicate JSON field"):
        PaperRiskSessionLatch.from_json_bytes(duplicate)

    payload = json.loads(raw)
    payload["maximum_daily_loss_fraction"] = 0.0
    tampered = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    with pytest.raises(ValueError, match="content hash"):
        PaperRiskSessionLatch.from_json_bytes(tampered)
