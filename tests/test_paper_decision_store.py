from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import gpt_quant._paper_decision_store_core as core_module
import gpt_quant.paper_decision_store as store_module
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.paper_decision_store import (
    PaperOrderDecision,
    initialize_paper_order_decision_store,
    load_paper_order_decision,
    pending_target_position_intents,
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


def _decision(
    target: TargetPositionIntent,
    *,
    outcome: str = "planned",
    quantity: str = "0.001",
    decided_at: datetime | None = None,
    market_observed_at: datetime | None = None,
) -> PaperOrderDecision:
    decision_time = decided_at or target.decision_not_before_utc + timedelta(seconds=2)
    market_time = market_observed_at or decision_time - timedelta(seconds=1)
    rejected = outcome == "rejected"
    return PaperOrderDecision(
        target_intent_id=target.intent_id,
        instrument_id=target.instrument_id,
        decided_at_utc=decision_time,
        market_observed_at_utc=market_time,
        outcome=outcome,
        reason_code="pretrade_passed" if not rejected else "intent_expired",
        order_type="none" if rejected else "market",
        side="none" if rejected else "buy",
        base_quantity="0" if rejected else quantity,
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


def _paths(tmp_path: Path) -> tuple[Path, Path, TargetPositionIntent]:
    target_path = tmp_path / "target-intents.jsonl"
    decision_directory = tmp_path / "paper-decisions"
    target = _target()
    record_target_position_intent(target_path, target)
    initialize_paper_order_decision_store(target_path, decision_directory)
    return target_path, decision_directory, target


def test_paper_decision_atomically_consumes_target_and_is_idempotent(tmp_path: Path) -> None:
    target_path, decision_directory, target = _paths(tmp_path)
    decision = _decision(target)

    assert pending_target_position_intents(target_path, decision_directory) == (target,)
    recorded = record_paper_order_decision(target_path, decision_directory, decision)
    path = decision_directory / f"{target.intent_id}.json"

    assert recorded == decision
    assert load_paper_order_decision(path) == decision
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert pending_target_position_intents(target_path, decision_directory) == ()
    assert record_paper_order_decision(target_path, decision_directory, decision) == decision


def test_duplicate_delivery_with_different_quantity_fails_closed(tmp_path: Path) -> None:
    target_path, decision_directory, target = _paths(tmp_path)
    first = _decision(target, quantity="0.001")
    conflicting = _decision(target, quantity="0.002")
    record_paper_order_decision(target_path, decision_directory, first)
    path = decision_directory / f"{target.intent_id}.json"
    before = path.read_bytes()

    with pytest.raises(ValueError, match="conflicts with the consumed target intent"):
        record_paper_order_decision(target_path, decision_directory, conflicting)

    assert path.read_bytes() == before
    assert pending_target_position_intents(target_path, decision_directory) == ()


def test_planned_decision_requires_active_intent_and_post_activation_market_data(
    tmp_path: Path,
) -> None:
    target_path, decision_directory, target = _paths(tmp_path)

    with pytest.raises(ValueError, match="cannot precede target activation"):
        record_paper_order_decision(
            target_path,
            decision_directory,
            _decision(target, decided_at=target.signal_bar_close_utc),
        )
    with pytest.raises(ValueError, match="post-activation market snapshot"):
        record_paper_order_decision(
            target_path,
            decision_directory,
            _decision(
                target,
                market_observed_at=target.signal_bar_close_utc,
            ),
        )
    with pytest.raises(ValueError, match="expired"):
        record_paper_order_decision(
            target_path,
            decision_directory,
            _decision(target, decided_at=target.expires_at_utc),
        )

    assert pending_target_position_intents(target_path, decision_directory) == (target,)


def test_expired_target_can_be_consumed_only_as_rejection(tmp_path: Path) -> None:
    target_path, decision_directory, target = _paths(tmp_path)
    rejected = _decision(
        target,
        outcome="rejected",
        decided_at=target.expires_at_utc + timedelta(seconds=1),
        market_observed_at=target.expires_at_utc,
    )

    assert record_paper_order_decision(target_path, decision_directory, rejected) == rejected
    assert pending_target_position_intents(target_path, decision_directory) == ()


def test_failed_publication_leaves_target_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path, decision_directory, target = _paths(tmp_path)
    decision = _decision(target)

    def fail_replace(source: object, destination: object) -> None:
        raise OSError("simulated commit failure")

    monkeypatch.setattr(store_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated commit failure"):
        record_paper_order_decision(target_path, decision_directory, decision)

    assert pending_target_position_intents(target_path, decision_directory) == (target,)
    assert not list(decision_directory.glob("*.json"))


def test_cost_components_remain_separate_and_canonical(tmp_path: Path) -> None:
    target_path, decision_directory, target = _paths(tmp_path)
    decision = record_paper_order_decision(
        target_path,
        decision_directory,
        _decision(target),
    )
    serialized = decision.to_json_bytes()

    assert b'"exchange_fee_bps":"5"' in serialized
    assert b'"spread_bps":"1.25"' in serialized
    assert b'"slippage_bps":"0.5"' in serialized
    assert b'"market_impact_bps":"0.25"' in serialized
    assert b"all_in" not in serialized


def test_store_rejects_unknown_decision_file(tmp_path: Path) -> None:
    target_path, decision_directory, target = _paths(tmp_path)
    decision = _decision(target)
    record_paper_order_decision(target_path, decision_directory, decision)
    original = decision_directory / f"{target.intent_id}.json"
    unexpected = decision_directory / f"{'0' * 64}.json"
    unexpected.write_bytes(original.read_bytes())
    os.chmod(unexpected, 0o600)

    with pytest.raises(ValueError, match="unknown target intent"):
        pending_target_position_intents(target_path, decision_directory)


def test_replay_is_target_ordered_and_content_addressed(tmp_path: Path) -> None:
    target_path, decision_directory, first_target = _paths(tmp_path)
    second_open = first_target.signal_bar_open_utc + timedelta(days=1)
    second_target = TargetPositionIntent(
        instrument_id=first_target.instrument_id,
        bar=first_target.bar,
        strategy_id=first_target.strategy_id,
        strategy_revision=first_target.strategy_revision,
        source_data_sha256=first_target.source_data_sha256,
        config_sha256=first_target.config_sha256,
        signal_bar_open_utc=second_open,
        signal_bar_close_utc=second_open + timedelta(days=1),
        decision_not_before_utc=second_open + timedelta(days=1, seconds=1),
        expires_at_utc=second_open + timedelta(days=2),
        target_position=0.25,
        minimum_position=0.0,
        maximum_position=1.0,
    )
    record_target_position_intent(target_path, second_target)
    second_decision = _decision(second_target, quantity="0.002")
    first_decision = _decision(first_target)

    record_paper_order_decision(target_path, decision_directory, second_decision)
    record_paper_order_decision(target_path, decision_directory, first_decision)
    replay = replay_paper_order_decision_store(target_path, decision_directory)

    assert replay.decisions == (first_decision, second_decision)
    assert replay.pending_target_intents == ()
    assert (
        replay.target_journal_sha256
        == hashlib.sha256(first_target.to_json_bytes() + second_target.to_json_bytes()).hexdigest()
    )
    expected_evidence = {
        "schema_version": 1,
        "target_journal_sha256": replay.target_journal_sha256,
        "decision_ids": [first_decision.decision_id, second_decision.decision_id],
        "pending_target_intent_ids": [],
    }
    expected_bytes = json.dumps(
        expected_evidence,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert replay.store_sha256 == hashlib.sha256(expected_bytes).hexdigest()
    assert replay_paper_order_decision_store(target_path, decision_directory) == replay


def test_replay_rejects_canonical_decision_that_precedes_target_activation(
    tmp_path: Path,
) -> None:
    target_path, decision_directory, target = _paths(tmp_path)
    invalid = _decision(
        target,
        outcome="rejected",
        decided_at=target.signal_bar_close_utc,
        market_observed_at=target.signal_bar_close_utc,
    )
    path = decision_directory / f"{target.intent_id}.json"
    path.write_bytes(invalid.to_json_bytes())
    os.chmod(path, 0o600)

    with pytest.raises(ValueError, match="cannot precede target activation"):
        replay_paper_order_decision_store(target_path, decision_directory)
    with pytest.raises(ValueError, match="cannot precede target activation"):
        pending_target_position_intents(target_path, decision_directory)


def test_decision_record_size_limit_accepts_exact_boundary_and_rejects_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path, decision_directory, target = _paths(tmp_path)
    decision = record_paper_order_decision(
        target_path,
        decision_directory,
        _decision(target),
    )
    path = decision_directory / f"{target.intent_id}.json"
    payload = path.read_bytes()
    monkeypatch.setattr(core_module, "_MAX_DECISION_RECORD_BYTES", len(payload))

    assert load_paper_order_decision(path) == decision
    assert (
        replay_paper_order_decision_store(target_path, decision_directory).decisions
        == (decision,)
    )

    path.write_bytes(payload + b"\n")
    os.chmod(path, 0o600)
    with pytest.raises(ValueError, match="exceeds the maximum record size"):
        load_paper_order_decision(path)
    with pytest.raises(ValueError, match="exceeds the maximum record size"):
        replay_paper_order_decision_store(target_path, decision_directory)


def test_decision_record_read_limit_rejects_growth_after_fstat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "decision.json"
    path.write_bytes(b"x")
    os.chmod(path, 0o600)
    descriptor = os.open(path, os.O_RDONLY)
    chunks = iter((b"a" * 8, b"b", b""))
    monkeypatch.setattr(core_module, "_MAX_DECISION_RECORD_BYTES", 8)

    def read_next_chunk(_descriptor: int, _size: int) -> bytes:
        return next(chunks)

    monkeypatch.setattr(core_module.os, "read", read_next_chunk)
    try:
        with pytest.raises(ValueError, match="exceeds the maximum record size"):
            core_module._read_decision_descriptor(descriptor, "paper order decision")
    finally:
        os.close(descriptor)
