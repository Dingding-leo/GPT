from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.paper_decision_store import (
    PaperOrderDecision,
    initialize_paper_order_decision_store,
    record_paper_order_decision,
    replay_paper_order_decision_store,
)
from gpt_quant.target_intent_journal import record_target_position_intent


def _target() -> TargetPositionIntent:
    signal_open = datetime(2026, 7, 21, tzinfo=UTC)
    signal_close = signal_open + timedelta(days=1)
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-5bps-walk-forward",
        strategy_revision="bd3bf844d0c37e2e65d6591cb2a3c4a03e6e45c3",
        source_data_sha256="ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149",
        config_sha256="a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822",
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
        instrument_snapshot_sha256="7bde34f3315c0774f12544c730b4fc19baa3399285aef9cabbb6bbf25869f31b",
        market_snapshot_sha256="3f0366f59e908cbd0366be93a46d13c74a80d753e6452177ac8341d409c54250",
        portfolio_state_before_sha256="821ce470b97bfbc53529bc2f7a95bded56d5e808a4d628728285a4ffd01c27c9",
        risk_state_before_sha256="6ab0010d4ce8090657d35599267fd73910f2d9a6d9566661a3f7ed9e566f5539",
        exchange_fee_bps="5",
        spread_bps="1.25",
        slippage_bps="0.5",
        market_impact_bps="0.25",
        latency_ms=80,
    )


def test_store_rejects_group_world_readable_directory_before_state_access(
    tmp_path: Path,
) -> None:
    target_path = tmp_path / "target-intents.jsonl"
    decision_directory = tmp_path / "paper-decisions"
    target = _target()
    record_target_position_intent(target_path, target)
    decision_directory.mkdir(mode=0o700)
    decision_directory.chmod(0o755)

    with pytest.raises(ValueError, match="owner-only 0700"):
        initialize_paper_order_decision_store(target_path, decision_directory)
    with pytest.raises(ValueError, match="owner-only 0700"):
        record_paper_order_decision(target_path, decision_directory, _decision(target))
    with pytest.raises(ValueError, match="owner-only 0700"):
        replay_paper_order_decision_store(target_path, decision_directory)

    assert not list(decision_directory.iterdir())
