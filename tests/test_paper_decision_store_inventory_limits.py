from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import gpt_quant._paper_decision_store_core as core_module
import gpt_quant.paper_decision_store as store_module
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.paper_decision_store import (
    PaperOrderDecision,
    initialize_paper_order_decision_store,
    pending_target_position_intents,
    record_paper_order_decision,
    replay_paper_order_decision_store,
)
from gpt_quant.target_intent_journal import record_target_position_intent


def _target(*, day_offset: int = 0) -> TargetPositionIntent:
    signal_open = datetime(2026, 7, 21, tzinfo=UTC) + timedelta(days=day_offset)
    signal_close = signal_open + timedelta(days=1)
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-5bps-walk-forward",
        strategy_revision="b" * 40,
        source_data_sha256="a" * 64,
        config_sha256="c" * 64,
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
        instrument_snapshot_sha256="d" * 64,
        market_snapshot_sha256="e" * 64,
        portfolio_state_before_sha256="f" * 64,
        risk_state_before_sha256="1" * 64,
        exchange_fee_bps="5",
        spread_bps="1.25",
        slippage_bps="0.5",
        market_impact_bps="0.25",
        latency_ms=80,
    )


def _populated_store(
    tmp_path: Path,
) -> tuple[Path, Path, TargetPositionIntent, PaperOrderDecision]:
    target_path = tmp_path / "target-intents.jsonl"
    decision_directory = tmp_path / "paper-decisions"
    target = _target()
    record_target_position_intent(target_path, target)
    initialize_paper_order_decision_store(target_path, decision_directory)
    decision = record_paper_order_decision(target_path, decision_directory, _decision(target))
    return target_path, decision_directory, target, decision


def test_inventory_accepts_exact_limits_and_rejects_extra_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path, decision_directory, _target_intent, decision = _populated_store(tmp_path)
    monkeypatch.setattr(core_module, "_MAX_DECISION_STORE_ENTRIES", 2)
    monkeypatch.setattr(core_module, "_MAX_DECISION_STORE_RECORDS", 1)

    assert replay_paper_order_decision_store(target_path, decision_directory).decisions == (
        decision,
    )
    assert pending_target_position_intents(target_path, decision_directory) == ()

    (decision_directory / "unexpected-entry").write_bytes(b"unexpected")
    with pytest.raises(ValueError, match="exceeds the maximum entry count"):
        replay_paper_order_decision_store(target_path, decision_directory)
    with pytest.raises(ValueError, match="exceeds the maximum entry count"):
        pending_target_position_intents(target_path, decision_directory)


def test_inventory_rejects_decision_count_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path, decision_directory, _target_intent, decision = _populated_store(tmp_path)
    duplicate = decision_directory / f"{'0' * 64}.json"
    duplicate.write_bytes(decision.to_json_bytes())
    os.chmod(duplicate, 0o600)
    monkeypatch.setattr(core_module, "_MAX_DECISION_STORE_ENTRIES", 3)
    monkeypatch.setattr(core_module, "_MAX_DECISION_STORE_RECORDS", 1)

    with pytest.raises(ValueError, match="exceeds the maximum decision count"):
        replay_paper_order_decision_store(target_path, decision_directory)
    with pytest.raises(ValueError, match="exceeds the maximum decision count"):
        pending_target_position_intents(target_path, decision_directory)


def test_initialization_inventory_accepts_exact_limit_and_rejects_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "target-intents.jsonl"
    decision_directory = tmp_path / "paper-decisions"
    record_target_position_intent(target_path, _target())
    expected_genesis = initialize_paper_order_decision_store(target_path, decision_directory)

    (decision_directory / "recovery-note").write_bytes(b"bounded")
    monkeypatch.setattr(core_module, "_MAX_DECISION_STORE_ENTRIES", 2)
    actual_genesis = initialize_paper_order_decision_store(target_path, decision_directory)
    assert actual_genesis == expected_genesis

    (decision_directory / "unexpected-entry").write_bytes(b"excess")
    with pytest.raises(ValueError, match="exceeds the maximum entry count"):
        initialize_paper_order_decision_store(target_path, decision_directory)


def test_initialization_genesis_byte_limit_is_checked_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "target-intents.jsonl"
    record_target_position_intent(target_path, _target())
    payload_size = len(store_module._genesis_payload(target_path))

    accepted_directory = tmp_path / "accepted-paper-decisions"
    monkeypatch.setattr(store_module, "_GENESIS_MAX_BYTES", payload_size)
    initialize_paper_order_decision_store(target_path, accepted_directory)

    rejected_directory = tmp_path / "rejected-paper-decisions"
    monkeypatch.setattr(store_module, "_GENESIS_MAX_BYTES", payload_size - 1)
    with pytest.raises(ValueError, match="genesis exceeds the size limit"):
        initialize_paper_order_decision_store(target_path, rejected_directory)

    assert not rejected_directory.exists()
    assert not (tmp_path / store_module._claim_name(rejected_directory)).exists()


def test_initialization_genesis_target_limit_is_checked_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(store_module, "_GENESIS_MAX_TARGETS", 1)

    accepted_target_path = tmp_path / "accepted-target-intents.jsonl"
    record_target_position_intent(accepted_target_path, _target())
    initialize_paper_order_decision_store(
        accepted_target_path,
        tmp_path / "accepted-target-limit-store",
    )

    rejected_target_path = tmp_path / "rejected-target-intents.jsonl"
    record_target_position_intent(rejected_target_path, _target())
    record_target_position_intent(rejected_target_path, _target(day_offset=2))
    rejected_directory = tmp_path / "rejected-target-limit-store"
    with pytest.raises(ValueError, match="genesis exceeds the target count limit"):
        initialize_paper_order_decision_store(rejected_target_path, rejected_directory)

    assert not rejected_directory.exists()
    assert not (tmp_path / store_module._claim_name(rejected_directory)).exists()
