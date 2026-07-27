from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import gpt_quant.paper_decision_store as store_module
import gpt_quant.target_intent_journal as journal_module
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.paper_decision_store import initialize_paper_order_decision_store
from gpt_quant.target_intent_journal import (
    load_target_position_intent_journal,
    record_target_position_intent,
)


def _intent(*, day_offset: int = 0) -> TargetPositionIntent:
    signal_open = datetime(2026, 7, 21, tzinfo=UTC) + timedelta(days=day_offset)
    signal_close = signal_open + timedelta(hours=1)
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1H",
        strategy_id="canonical-5bps-walk-forward",
        strategy_revision="b" * 40,
        source_data_sha256="a" * 64,
        config_sha256="c" * 64,
        signal_bar_open_utc=signal_open,
        signal_bar_close_utc=signal_close,
        decision_not_before_utc=signal_close + timedelta(seconds=1),
        expires_at_utc=signal_close + timedelta(hours=1),
        target_position=0.5,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def test_journal_byte_limit_is_enforced_before_and_during_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    first_payload = _intent().to_json_bytes()
    second_payload = _intent(day_offset=1).to_json_bytes()
    path.write_bytes(first_payload)
    path.chmod(0o600)

    monkeypatch.setattr(journal_module, "_MAX_JOURNAL_BYTES", len(first_payload))
    assert load_target_position_intent_journal(path).count == 1

    monkeypatch.setattr(journal_module, "_MAX_JOURNAL_BYTES", len(first_payload) - 1)

    def fail_read(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("oversized journal must be rejected before reading")

    monkeypatch.setattr(journal_module.os, "read", fail_read)
    with pytest.raises(ValueError, match="exceeds the maximum byte size"):
        load_target_position_intent_journal(path)

    monkeypatch.undo()
    path.write_bytes(first_payload + second_payload)
    path.chmod(0o600)
    monkeypatch.setattr(journal_module, "_MAX_JOURNAL_BYTES", len(first_payload))
    real_fstat = os.fstat

    def underreport_size(descriptor: int) -> os.stat_result:
        values = list(real_fstat(descriptor))
        values[6] = len(first_payload)
        return os.stat_result(values)

    monkeypatch.setattr(journal_module.os, "fstat", underreport_size)
    with pytest.raises(ValueError, match="exceeds the maximum byte size"):
        load_target_position_intent_journal(path)


def test_journal_record_limit_and_publication_are_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    first = _intent()
    second = _intent(day_offset=1)
    monkeypatch.setattr(journal_module, "_MAX_JOURNAL_RECORDS", 1)

    journal = record_target_position_intent(path, first)
    before = path.read_bytes()
    assert journal.count == 1
    assert load_target_position_intent_journal(path) == journal

    with pytest.raises(ValueError, match="exceeds the maximum record count"):
        record_target_position_intent(path, second)
    assert path.read_bytes() == before

    path.write_bytes(first.to_json_bytes() + second.to_json_bytes())
    path.chmod(0o600)
    with pytest.raises(ValueError, match="exceeds the maximum record count"):
        load_target_position_intent_journal(path)


def test_journal_byte_limit_blocks_publication_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    first = _intent()
    second = _intent(day_offset=1)
    first_size = len(first.to_json_bytes())
    monkeypatch.setattr(journal_module, "_MAX_JOURNAL_BYTES", first_size)

    record_target_position_intent(path, first)
    before = path.read_bytes()
    with pytest.raises(ValueError, match="exceeds the maximum byte size"):
        record_target_position_intent(path, second)
    assert path.read_bytes() == before
    assert load_target_position_intent_journal(path).intents == (first,)


def test_intent_record_byte_limit_is_enforced_on_load_and_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    target = _intent()
    payload = target.to_json_bytes()
    path.write_bytes(payload)
    path.chmod(0o600)

    monkeypatch.setattr(journal_module, "_MAX_INTENT_RECORD_BYTES", len(payload))
    assert load_target_position_intent_journal(path).intents == (target,)

    monkeypatch.setattr(journal_module, "_MAX_INTENT_RECORD_BYTES", len(payload) - 1)
    with pytest.raises(ValueError, match="exceeds the maximum record byte size"):
        load_target_position_intent_journal(path)

    path.unlink()
    with pytest.raises(ValueError, match="exceeds the maximum record byte size"):
        record_target_position_intent(path, target)
    assert not path.exists()


def test_store_initialization_inherits_target_journal_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = tmp_path / "target-intents.jsonl"
    target = _intent()
    payload = target.to_json_bytes()
    target_path.write_bytes(payload)
    target_path.chmod(0o600)

    accepted_directory = tmp_path / "accepted-paper-decisions"
    monkeypatch.setattr(journal_module, "_MAX_JOURNAL_BYTES", len(payload))
    initialize_paper_order_decision_store(target_path, accepted_directory)

    rejected_directory = tmp_path / "rejected-paper-decisions"
    monkeypatch.setattr(journal_module, "_MAX_JOURNAL_BYTES", len(payload) - 1)
    with pytest.raises(ValueError, match="exceeds the maximum byte size"):
        initialize_paper_order_decision_store(target_path, rejected_directory)

    assert not rejected_directory.exists()
    assert not (tmp_path / store_module._claim_name(rejected_directory)).exists()


def test_journal_requires_private_owner_only_permissions(tmp_path: Path) -> None:
    path = tmp_path / "target-intents.jsonl"
    payload = _intent().to_json_bytes()
    path.write_bytes(payload)

    for mode in (0o660, 0o666, 0o644):
        path.chmod(mode)
        with pytest.raises(ValueError, match="owner-only 0600 permissions"):
            load_target_position_intent_journal(path)

    path.chmod(0o600)
    assert load_target_position_intent_journal(path).count == 1


def test_journal_rejects_foreign_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    record_target_position_intent(path, _intent())
    real_fstat = os.fstat

    def report_foreign_owner(descriptor: int) -> os.stat_result:
        result = real_fstat(descriptor)
        if not stat.S_ISREG(result.st_mode):
            return result
        values = list(result)
        values[4] += 1
        return os.stat_result(values)

    monkeypatch.setattr(journal_module.os, "fstat", report_foreign_owner)
    with pytest.raises(ValueError, match="owned by the current user"):
        load_target_position_intent_journal(path)


def test_journal_publication_and_store_replay_preserve_private_mode(tmp_path: Path) -> None:
    path = tmp_path / "target-intents.jsonl"
    target = _intent()
    journal = record_target_position_intent(path, target)

    assert path.stat().st_mode & 0o777 == 0o600
    assert load_target_position_intent_journal(path) == journal

    decision_directory = tmp_path / "paper-decisions"
    initialize_paper_order_decision_store(path, decision_directory)

    path.chmod(0o666)
    with pytest.raises(ValueError, match="owner-only 0600 permissions"):
        initialize_paper_order_decision_store(path, tmp_path / "second-paper-decisions")
    with pytest.raises(ValueError, match="owner-only 0600 permissions"):
        store_module.replay_paper_order_decision_store(path, decision_directory)


@pytest.mark.parametrize("mode", (0o770, 0o777))
def test_journal_rejects_group_or_world_writable_parent_before_creation(
    tmp_path: Path,
    mode: int,
) -> None:
    parent = tmp_path / f"unsafe-{mode:o}"
    parent.mkdir(mode=0o700)
    parent.chmod(mode)
    path = parent / "target-intents.jsonl"
    lock_path = parent / f".{path.name}.lock"

    with pytest.raises(
        ValueError,
        match="parent directory must not be group/world writable",
    ):
        record_target_position_intent(path, _intent())

    assert not path.exists()
    assert not lock_path.exists()

    path.write_bytes(_intent().to_json_bytes())
    path.chmod(0o600)
    with pytest.raises(
        ValueError,
        match="parent directory must not be group/world writable",
    ):
        load_target_position_intent_journal(path)


def test_journal_rejects_foreign_owned_parent_before_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "foreign-parent"
    parent.mkdir(mode=0o700)
    path = parent / "target-intents.jsonl"
    lock_path = parent / f".{path.name}.lock"
    real_fstat = os.fstat

    def report_foreign_parent(descriptor: int) -> os.stat_result:
        result = real_fstat(descriptor)
        if not stat.S_ISDIR(result.st_mode):
            return result
        values = list(result)
        values[4] += 1
        return os.stat_result(values)

    monkeypatch.setattr(journal_module.os, "fstat", report_foreign_parent)
    with pytest.raises(
        ValueError,
        match="parent directory must be owned by the current user",
    ):
        record_target_position_intent(path, _intent())

    assert not path.exists()
    assert not lock_path.exists()


def test_untrusted_parent_cannot_reset_missing_committed_journal(tmp_path: Path) -> None:
    parent = tmp_path / "journal-state"
    parent.mkdir(mode=0o700)
    path = parent / "target-intents.jsonl"
    lock_path = parent / f".{path.name}.lock"
    first = _intent()
    second = _intent(day_offset=1)

    record_target_position_intent(path, first)
    parent.chmod(0o777)
    path.unlink()
    try:
        with pytest.raises(
            ValueError,
            match="parent directory must not be group/world writable",
        ):
            record_target_position_intent(path, second)
        assert not path.exists()
        assert not lock_path.exists()
    finally:
        parent.chmod(0o700)


def test_store_initialization_and_replay_reject_untrusted_journal_parent(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "journal-state"
    parent.mkdir(mode=0o700)
    path = parent / "target-intents.jsonl"
    record_target_position_intent(path, _intent())
    decision_directory = parent / "paper-decisions"
    initialize_paper_order_decision_store(path, decision_directory)

    parent.chmod(0o777)
    try:
        with pytest.raises(
            ValueError,
            match="parent directory must not be group/world writable",
        ):
            initialize_paper_order_decision_store(
                path,
                parent / "second-paper-decisions",
            )
        with pytest.raises(
            ValueError,
            match="parent directory must not be group/world writable",
        ):
            store_module.replay_paper_order_decision_store(path, decision_directory)
    finally:
        parent.chmod(0o700)


def test_journal_load_rejects_path_replacement_during_deserialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    replacement_path = tmp_path / "replacement-target-intents.jsonl"
    original = _intent()
    replacement = _intent(day_offset=1)
    record_target_position_intent(path, original)
    replacement_path.write_bytes(replacement.to_json_bytes())
    replacement_path.chmod(0o600)

    original_parser = TargetPositionIntent.from_json_bytes
    replaced = False

    def replace_path_then_parse(
        cls: type[TargetPositionIntent],
        value: bytes | str,
    ) -> TargetPositionIntent:
        del cls
        nonlocal replaced
        if not replaced:
            replaced = True
            os.replace(replacement_path, path)
        return original_parser(value)

    monkeypatch.setattr(
        TargetPositionIntent,
        "from_json_bytes",
        classmethod(replace_path_then_parse),
    )

    with pytest.raises(RuntimeError, match="path changed during replay"):
        load_target_position_intent_journal(path)

    assert replaced
    assert path.read_bytes() == replacement.to_json_bytes()


def test_store_replay_inherits_journal_path_identity_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    replacement_path = tmp_path / "replacement-target-intents.jsonl"
    original = _intent()
    replacement = _intent(day_offset=1)
    record_target_position_intent(path, original)
    decision_directory = tmp_path / "paper-decisions"
    initialize_paper_order_decision_store(path, decision_directory)
    replacement_path.write_bytes(replacement.to_json_bytes())
    replacement_path.chmod(0o600)

    original_parser = TargetPositionIntent.from_json_bytes
    replaced = False

    def replace_path_then_parse(
        cls: type[TargetPositionIntent],
        value: bytes | str,
    ) -> TargetPositionIntent:
        del cls
        nonlocal replaced
        if not replaced:
            replaced = True
            os.replace(replacement_path, path)
        return original_parser(value)

    monkeypatch.setattr(
        TargetPositionIntent,
        "from_json_bytes",
        classmethod(replace_path_then_parse),
    )

    with pytest.raises(RuntimeError, match="path changed during replay"):
        store_module.replay_paper_order_decision_store(path, decision_directory)

    assert replaced
    assert path.read_bytes() == replacement.to_json_bytes()
