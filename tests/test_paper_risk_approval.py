from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.paper_risk_approval import (
    PaperRiskApproval,
    RiskApprovedExposure,
    create_paper_risk_approval,
    verify_paper_risk_approval,
)
from gpt_quant.paper_risk_kill_switch import (
    InstrumentExposure,
    PaperRiskKillSwitchDecision,
    PaperRiskKillSwitchPolicy,
    PaperRiskStateSnapshot,
    ProposedInstrumentExposure,
    evaluate_paper_risk_kill_switch,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1h-raw-20260724"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "228828e32a5a43f0010a326ab65c368dbdc6202a158738b0e9956ad7c6393137"
_CONFIG_SHA256 = hashlib.sha256(b"paper-risk-approval-target-replay-v1").hexdigest()


def _real_okx_mark() -> tuple[datetime, float, str]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    assert hashlib.sha256(rows_bytes).hexdigest() == _EXPECTED_FIXTURE_SHA256
    assert metadata["fixture_rows_sha256"] == _EXPECTED_FIXTURE_SHA256
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1H"

    rows = json.loads(rows_bytes)
    confirmed = next(row for row in rows if row[8] == "1")
    observed_at = datetime.fromtimestamp(int(confirmed[0]) / 1000, tz=UTC)
    return observed_at, float(confirmed[4]), _EXPECTED_FIXTURE_SHA256


def _state(*, current_fraction: float) -> tuple[PaperRiskStateSnapshot, datetime]:
    market_observed_at, real_mark, source_hash = _real_okx_mark()
    evaluated_at = market_observed_at + timedelta(seconds=2)
    state_hash = hashlib.sha256(
        json.dumps(
            {
                "current_fraction": current_fraction,
                "evaluated_at": evaluated_at.isoformat(),
                "real_mark": real_mark,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return (
        PaperRiskStateSnapshot(
            observed_at_utc=evaluated_at - timedelta(seconds=1),
            session_start_utc=market_observed_at,
            market_data_observed_at_utc=market_observed_at,
            session_start_equity=real_mark,
            peak_equity=real_mark * 1.02,
            current_equity=real_mark * current_fraction,
            daily_underlying_turnover=0.25,
            instrument_exposures=(InstrumentExposure("BTC-USDT", 0.50),),
            portfolio_state_sha256=state_hash,
            market_data_source_sha256=source_hash,
        ),
        evaluated_at,
    )


def _target(
    snapshot: PaperRiskStateSnapshot,
    evaluated_at: datetime,
    *,
    target_position: float = 0.40,
    expires_at_utc: datetime | None = None,
) -> TargetPositionIntent:
    signal_close = snapshot.market_data_observed_at_utc
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1H",
        strategy_id="paper-risk-approval-target-replay",
        strategy_revision="1" * 40,
        source_data_sha256=snapshot.market_data_source_sha256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=signal_close - timedelta(hours=1),
        signal_bar_close_utc=signal_close,
        decision_not_before_utc=signal_close,
        expires_at_utc=expires_at_utc or evaluated_at + timedelta(hours=1),
        target_position=target_position,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def _policy() -> PaperRiskKillSwitchPolicy:
    return PaperRiskKillSwitchPolicy(
        daily_loss_trigger_fraction=0.05,
        drawdown_trigger_fraction=0.10,
        daily_underlying_turnover_trigger=1.0,
        maximum_state_age_seconds=5.0,
        maximum_market_data_age_seconds=5.0,
    )


def test_allowed_approval_round_trips_and_replays_exact_target_and_risk_inputs() -> None:
    snapshot, evaluated_at = _state(current_fraction=1.0)
    target = _target(snapshot, evaluated_at)
    policy = _policy()
    proposals = (ProposedInstrumentExposure("BTC-USDT", target.target_position),)

    approval = create_paper_risk_approval(
        target,
        proposals,
        snapshot=snapshot,
        policy=policy,
        evaluated_at_utc=evaluated_at,
    )
    replayed = PaperRiskApproval.from_json_bytes(approval.to_json_bytes())
    reconstructed = verify_paper_risk_approval(
        replayed,
        target=target,
        snapshot=snapshot,
        policy=policy,
    )

    assert replayed == approval
    assert reconstructed.allowed is True
    assert reconstructed.decision_id == approval.risk_decision_id
    assert approval.target_intent_id == target.intent_id
    assert approval.snapshot_id == snapshot.snapshot_id
    assert approval.policy_id == policy.policy_id
    assert len(approval.approval_id) == 64


def test_approval_bytes_reject_changed_risk_decision_identity() -> None:
    snapshot, evaluated_at = _state(current_fraction=1.0)
    target = _target(snapshot, evaluated_at)
    approval = create_paper_risk_approval(
        target,
        (ProposedInstrumentExposure("BTC-USDT", target.target_position),),
        snapshot=snapshot,
        policy=_policy(),
        evaluated_at_utc=evaluated_at,
    )
    payload = json.loads(approval.to_json_bytes())
    payload["risk_decision_id"] = hashlib.sha256(b"substituted-risk-decision").hexdigest()
    tampered = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"

    with pytest.raises(ValueError, match="ID does not match"):
        PaperRiskApproval.from_json_bytes(tampered)


def test_breached_state_cannot_mint_exposure_increase_approval() -> None:
    snapshot, evaluated_at = _state(current_fraction=0.94)
    target = _target(snapshot, evaluated_at, target_position=0.60)

    with pytest.raises(RuntimeError, match="risk kill switch rejected"):
        create_paper_risk_approval(
            target,
            (ProposedInstrumentExposure("BTC-USDT", target.target_position),),
            snapshot=snapshot,
            policy=_policy(),
            evaluated_at_utc=evaluated_at,
        )


def test_caller_forged_allowed_decision_cannot_be_promoted_without_replay() -> None:
    snapshot, evaluated_at = _state(current_fraction=0.94)
    target = _target(snapshot, evaluated_at, target_position=0.60)
    policy = _policy()
    proposals = (ProposedInstrumentExposure("BTC-USDT", target.target_position),)
    blocked = evaluate_paper_risk_kill_switch(
        proposals,
        snapshot=snapshot,
        policy=policy,
        evaluated_at_utc=evaluated_at,
    )
    assert blocked.allowed is False

    forged = PaperRiskKillSwitchDecision(
        decision_id=hashlib.sha256(b"forged-risk-approval").hexdigest(),
        evaluated_at_utc=blocked.evaluated_at_utc,
        snapshot_id=blocked.snapshot_id,
        policy_id=blocked.policy_id,
        mode="normal",
        active_triggers=(),
        exposure_increase_instruments=(),
        allowed=True,
        blockers=(),
        state_age_seconds=blocked.state_age_seconds,
        market_data_age_seconds=blocked.market_data_age_seconds,
        daily_loss_fraction=blocked.daily_loss_fraction,
        drawdown_fraction=blocked.drawdown_fraction,
        daily_underlying_turnover=blocked.daily_underlying_turnover,
        current_gross_exposure=blocked.current_gross_exposure,
        proposed_gross_exposure=blocked.proposed_gross_exposure,
        exposure_changes=blocked.exposure_changes,
    )
    forged.assert_allowed()

    forged_approval = PaperRiskApproval(
        target_intent_id=target.intent_id,
        evaluated_at_utc=forged.evaluated_at_utc,
        snapshot_id=forged.snapshot_id,
        policy_id=forged.policy_id,
        risk_decision_id=forged.decision_id,
        proposed_exposures=(RiskApprovedExposure("BTC-USDT", target.target_position),),
    )
    with pytest.raises(RuntimeError, match="risk kill switch rejected"):
        verify_paper_risk_approval(
            forged_approval,
            target=target,
            snapshot=snapshot,
            policy=policy,
        )


def test_expired_target_cannot_mint_or_replay_risk_approval() -> None:
    snapshot, evaluated_at = _state(current_fraction=1.0)
    target = _target(snapshot, evaluated_at, expires_at_utc=evaluated_at)
    policy = _policy()
    proposals = (ProposedInstrumentExposure("BTC-USDT", target.target_position),)

    with pytest.raises(ValueError, match="target-position intent has expired"):
        create_paper_risk_approval(
            target,
            proposals,
            snapshot=snapshot,
            policy=policy,
            evaluated_at_utc=evaluated_at,
        )

    decision = evaluate_paper_risk_kill_switch(
        proposals,
        snapshot=snapshot,
        policy=policy,
        evaluated_at_utc=evaluated_at,
    )
    decision.assert_allowed()
    replayed = PaperRiskApproval(
        target_intent_id=target.intent_id,
        evaluated_at_utc=decision.evaluated_at_utc,
        snapshot_id=decision.snapshot_id,
        policy_id=decision.policy_id,
        risk_decision_id=decision.decision_id,
        proposed_exposures=(RiskApprovedExposure("BTC-USDT", target.target_position),),
    )
    with pytest.raises(ValueError, match="target-position intent has expired"):
        verify_paper_risk_approval(
            replayed,
            target=target,
            snapshot=snapshot,
            policy=policy,
        )


def test_target_exposure_must_match_exact_target_position() -> None:
    snapshot, evaluated_at = _state(current_fraction=1.0)
    target = _target(snapshot, evaluated_at, target_position=0.40)

    with pytest.raises(ValueError, match="target exposure does not match"):
        create_paper_risk_approval(
            target,
            (ProposedInstrumentExposure("BTC-USDT", 0.60),),
            snapshot=snapshot,
            policy=_policy(),
            evaluated_at_utc=evaluated_at,
        )
