from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import gpt_quant.paper_decision_store as store_module
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.paper_decision_store import (
    PaperOrderDecision,
    initialize_paper_order_decision_store,
    record_paper_order_decision,
    replay_paper_order_decision_store,
)
from gpt_quant.target_intent_journal import record_target_position_intent

_SOURCE_SHA256 = "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_REVISION = "bd3bf844d0c37e2e65d6591cb2a3c4a03e6e45c3"
_INSTRUMENT_SHA256 = "7bde34f3315c0774f12544c730b4fc19baa3399285aef9cabbb6bbf25869f31b"
_MARKET_SHA256 = "3f0366f59e908cbd0366be93a46d13c74a80d753e6452177ac8341d409c54250"
_PORTFOLIO_SHA256 = "821ce470b97bfbc53529bc2f7a95bded56d5e808a4d628728285a4ffd01c27c9"
_RISK_SHA256 = "6ab0010d4ce8090657d35599267fd73910f2d9a6d9566661a3f7ed9e566f5539"


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
        instrument_snapshot_sha256=_INSTRUMENT_SHA256,
        market_snapshot_sha256=_MARKET_SHA256,
        portfolio_state_before_sha256=_PORTFOLIO_SHA256,
        risk_state_before_sha256=_RISK_SHA256,
        exchange_fee_bps="5",
        spread_bps="1.25",
        slippage_bps="0.5",
        market_impact_bps="0.25",
        latency_ms=80,
    )


def test_record_fails_closed_while_replay_snapshot_is_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "target-intents.jsonl"
    decision_directory = tmp_path / "paper-decisions"
    target = _target()
    decision = _decision(target)
    record_target_position_intent(target_path, target)
    initialize_paper_order_decision_store(target_path, decision_directory)

    replay_listed = threading.Event()
    release_replay = threading.Event()
    replay_results = []
    replay_errors: list[BaseException] = []
    real_listdir = store_module._core.os.listdir

    def pause_after_snapshot_list(directory_descriptor: int) -> list[str]:
        names = real_listdir(directory_descriptor)
        replay_listed.set()
        if not release_replay.wait(timeout=5):
            raise RuntimeError("timed out waiting to release replay")
        return names

    monkeypatch.setattr(store_module._core.os, "listdir", pause_after_snapshot_list)

    def run_replay() -> None:
        try:
            replay_results.append(
                replay_paper_order_decision_store(target_path, decision_directory)
            )
        except BaseException as exc:  # pragma: no cover - assertion reports details
            replay_errors.append(exc)

    replay_thread = threading.Thread(target=run_replay)
    replay_thread.start()
    assert replay_listed.wait(timeout=5)

    with pytest.raises(RuntimeError, match="paper order decision lock is held"):
        record_paper_order_decision(target_path, decision_directory, decision)
    assert not (decision_directory / f"{target.intent_id}.json").exists()

    release_replay.set()
    replay_thread.join(timeout=5)
    assert not replay_thread.is_alive()
    assert replay_errors == []
    assert replay_results[0].decisions == ()
    assert replay_results[0].pending_target_intents == (target,)

    monkeypatch.setattr(store_module._core.os, "listdir", real_listdir)
    assert record_paper_order_decision(target_path, decision_directory, decision) == decision
    final_replay = replay_paper_order_decision_store(target_path, decision_directory)
    assert final_replay.decisions == (decision,)
    assert final_replay.pending_target_intents == ()
