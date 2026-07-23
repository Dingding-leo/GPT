from __future__ import annotations

import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import gpt_quant.paper_decision_store as store_module
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.paper_decision_store import (
    PaperOrderDecision,
    replay_paper_order_decision_store,
)
from gpt_quant.target_intent_journal import record_target_position_intent

_SOURCE_SHA256 = "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_REVISION = "bd3bf844d0c37e2e65d6591cb2a3c4a03e6e45c3"
_DIGEST = "7bde34f3315c0774f12544c730b4fc19baa3399285aef9cabbb6bbf25869f31b"


def _target() -> TargetPositionIntent:
    signal_open = datetime(2026, 7, 21, tzinfo=UTC)
    signal_close = signal_open + timedelta(days=1)
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-5bps-walk-forward",
        strategy_revision=_REVISION,
        source_data_sha256=_SOURCE_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=signal_open,
        signal_bar_close_utc=signal_close,
        decision_not_before_utc=signal_close + timedelta(seconds=1),
        expires_at_utc=signal_close + timedelta(days=1),
        target_position=0.5,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def _decision(target: TargetPositionIntent) -> PaperOrderDecision:
    decided_at = target.decision_not_before_utc + timedelta(seconds=2)
    return PaperOrderDecision(
        target_intent_id=target.intent_id,
        instrument_id=target.instrument_id,
        decided_at_utc=decided_at,
        market_observed_at_utc=decided_at - timedelta(seconds=1),
        outcome="planned",
        reason_code="pretrade_passed",
        order_type="market",
        side="buy",
        base_quantity="0.001",
        instrument_snapshot_sha256=_DIGEST,
        market_snapshot_sha256=_DIGEST,
        portfolio_state_before_sha256=_DIGEST,
        risk_state_before_sha256=_DIGEST,
        exchange_fee_bps="5",
        spread_bps="1.25",
        slippage_bps="0.5",
        market_impact_bps="0.25",
        latency_ms=80,
    )


def test_missing_store_is_created_privately_before_replay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "target-intents.jsonl"
    decision_directory = tmp_path / "paper-decisions"
    target = _target()
    decision = _decision(target)
    record_target_position_intent(target_path, target)
    original_replay = store_module._core.replay_paper_order_decision_store

    def inject_if_missing(
        target_journal_path: str | Path,
        directory_path: str | Path,
    ):
        directory = Path(directory_path)
        if not directory.exists():
            directory.mkdir(mode=0o700)
            path = directory / f"{target.intent_id}.json"
            path.write_bytes(decision.to_json_bytes())
            path.chmod(0o600)
        return original_replay(target_journal_path, directory)

    monkeypatch.setattr(
        store_module._core,
        "replay_paper_order_decision_store",
        inject_if_missing,
    )

    replay = replay_paper_order_decision_store(target_path, decision_directory)

    assert replay.decisions == ()
    assert replay.pending_target_intents == (target,)
    assert stat.S_IMODE(decision_directory.stat().st_mode) == 0o700
    assert not list(decision_directory.iterdir())
