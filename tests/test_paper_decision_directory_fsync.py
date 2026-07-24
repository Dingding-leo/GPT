from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import gpt_quant.paper_decision_store as store_module
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.paper_decision_store import (
    PaperOrderDecision,
    pending_target_position_intents,
    record_paper_order_decision,
)
from gpt_quant.target_intent_journal import record_target_position_intent

_SOURCE_SHA256 = "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_REVISION = "bd3bf844d0c37e2e65d6591cb2a3c4a03e6e45c3"
_INSTRUMENT_SHA256 = "7bde34f3315c0774f12544c730b4fc19baa3399285aef9cabbb6bbf25869f31b"
_MARKET_SHA256 = "3f0366f59e908cbd0366be93a46d13c74a80d753e6452177ac8341d409c54250"
_PORTFOLIO_SHA256 = "821ce470b97bfbc53529bc2f7a95bded56d5e808a4d628728285a4ffd01c27c9"
_RISK_SHA256 = "6ab0010d4ce8090657d35599267fd73910f2d9a6d9566661a3f7ed9e566f5539"


def test_publication_fsyncs_store_parent_file_then_directory_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signal_open = datetime(2026, 7, 21, tzinfo=UTC)
    signal_close = signal_open + timedelta(days=1)
    target = TargetPositionIntent(
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
    target_path = tmp_path / "target-intents.jsonl"
    decision_directory = tmp_path / "paper-decisions"
    record_target_position_intent(target_path, target)
    decision_time = target.decision_not_before_utc + timedelta(seconds=2)
    decision = PaperOrderDecision(
        target_intent_id=target.intent_id,
        instrument_id=target.instrument_id,
        decided_at_utc=decision_time,
        market_observed_at_utc=decision_time - timedelta(seconds=1),
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
    parent_stat = tmp_path.stat()
    events: list[str] = []
    real_fsync = store_module.os.fsync
    real_replace = store_module.os.replace

    def trace_fsync(descriptor: int) -> None:
        opened = os.fstat(descriptor)
        if stat.S_ISDIR(opened.st_mode):
            parent_identity = (parent_stat.st_dev, parent_stat.st_ino)
            opened_identity = (opened.st_dev, opened.st_ino)
            events.append(
                "parent_directory_fsync"
                if opened_identity == parent_identity
                else "decision_directory_fsync"
            )
        else:
            events.append("file_fsync")
        real_fsync(descriptor)

    def trace_replace(source: object, destination: object) -> None:
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(store_module.os, "fsync", trace_fsync)
    monkeypatch.setattr(store_module.os, "replace", trace_replace)

    assert record_paper_order_decision(target_path, decision_directory, decision) == decision
    assert events == [
        "parent_directory_fsync",
        "file_fsync",
        "replace",
        "decision_directory_fsync",
    ]
    assert pending_target_position_intents(target_path, decision_directory) == ()
