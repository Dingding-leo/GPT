from __future__ import annotations

import hashlib
import multiprocessing
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import gpt_quant.target_intent_journal as journal_module
from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.target_intent_journal import (
    load_target_position_intent_journal,
    record_target_position_intent,
)

_SOURCE_SHA256 = "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_REVISION = "bd3bf844d0c37e2e65d6591cb2a3c4a03e6e45c3"
_CRASH_EXIT_CODE = 23


def _intent(
    *,
    day: int = 22,
    target_position: float = 0.5,
    decision_delay_seconds: int = 3,
) -> TargetPositionIntent:
    signal_open = datetime(2026, 7, day, tzinfo=UTC)
    signal_close = signal_open + timedelta(days=1)
    decision_time = signal_close + timedelta(seconds=decision_delay_seconds)
    return TargetPositionIntent(
        instrument_id="BTC-USDT",
        bar="1Dutc",
        strategy_id="canonical-5bps-walk-forward",
        strategy_revision=_REVISION,
        source_data_sha256=_SOURCE_SHA256,
        config_sha256=_CONFIG_SHA256,
        signal_bar_open_utc=signal_open,
        signal_bar_close_utc=signal_close,
        decision_not_before_utc=decision_time,
        expires_at_utc=signal_close + timedelta(days=1),
        target_position=target_position,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def _lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


def _write_private_journal(path: Path, payload: bytes) -> None:
    path.write_bytes(payload)
    path.chmod(0o600)


def _crash_during_intent_publication(path: str) -> None:
    def crash_publish(*args: object, **kwargs: object) -> None:
        os._exit(_CRASH_EXIT_CODE)

    journal_module.publish_payloads_atomically = crash_publish
    record_target_position_intent(Path(path), _intent(day=23, target_position=0.75))


def test_target_intent_journal_is_deterministic_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    earlier = _intent(day=22, target_position=0.25)
    later = _intent(day=23, target_position=0.75)

    record_target_position_intent(path, later)
    journal = record_target_position_intent(path, earlier)

    expected = earlier.to_json_bytes() + later.to_json_bytes()
    assert path.read_bytes() == expected
    assert journal.to_bytes() == expected
    assert journal.intents == (earlier, later)
    assert journal.count == 2
    assert journal.sha256 == hashlib.sha256(expected).hexdigest()
    assert load_target_position_intent_journal(path) == journal
    assert not _lock_path(path).exists()

    def fail_publish(*args: object, **kwargs: object) -> None:
        raise AssertionError("an identical intent must not rewrite the journal")

    monkeypatch.setattr(journal_module, "publish_payloads_atomically", fail_publish)
    assert record_target_position_intent(path, earlier) == journal
    assert path.read_bytes() == expected
    assert not _lock_path(path).exists()


def test_target_intent_journal_rejects_conflicting_target_for_one_signal(
    tmp_path: Path,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    first = _intent(target_position=0.25)
    conflicting = _intent(target_position=0.75)

    record_target_position_intent(path, first)
    before = path.read_bytes()

    with pytest.raises(ValueError, match="conflicting intents"):
        record_target_position_intent(path, conflicting)

    assert path.read_bytes() == before
    assert not _lock_path(path).exists()


def test_target_intent_journal_rejects_retry_with_new_observation_time(
    tmp_path: Path,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    first = _intent(target_position=0.25, decision_delay_seconds=3)
    retry = _intent(target_position=0.25, decision_delay_seconds=9)
    assert retry.intent_id != first.intent_id

    record_target_position_intent(path, first)
    before = path.read_bytes()

    with pytest.raises(ValueError, match="conflicting intents"):
        record_target_position_intent(path, retry)

    assert path.read_bytes() == before
    assert load_target_position_intent_journal(path).intents == (first,)
    assert not _lock_path(path).exists()


def test_target_intent_journal_rejects_concurrent_writer(tmp_path: Path) -> None:
    if journal_module._fcntl is None:
        pytest.skip("POSIX advisory locks are unavailable")

    path = tmp_path / "target-intents.jsonl"
    first = _intent(day=22, target_position=0.25)
    second = _intent(day=23, target_position=0.75)
    record_target_position_intent(path, first)
    before = path.read_bytes()

    lock_path = _lock_path(path)
    lock_path.write_bytes(b"held")
    descriptor = os.open(lock_path, os.O_RDWR)
    journal_module._fcntl.flock(
        descriptor,
        journal_module._fcntl.LOCK_EX | journal_module._fcntl.LOCK_NB,
    )
    try:
        with pytest.raises(RuntimeError, match="writer lock already exists"):
            record_target_position_intent(path, second)

        assert path.read_bytes() == before
        assert lock_path.read_bytes() == b"held"
    finally:
        journal_module._fcntl.flock(descriptor, journal_module._fcntl.LOCK_UN)
        os.close(descriptor)
        lock_path.unlink()


def test_target_intent_journal_recovers_after_crash_during_publication(
    tmp_path: Path,
) -> None:
    if journal_module._fcntl is None:
        pytest.skip("POSIX advisory locks are unavailable")

    path = tmp_path / "target-intents.jsonl"
    first = _intent(day=22, target_position=0.25)
    second = _intent(day=23, target_position=0.75)
    record_target_position_intent(path, first)
    before = path.read_bytes()

    process = multiprocessing.get_context("fork").Process(
        target=_crash_during_intent_publication,
        args=(str(path),),
    )
    process.start()
    process.join(timeout=10)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("crash simulation did not terminate")

    assert process.exitcode == _CRASH_EXIT_CODE
    assert path.read_bytes() == before
    assert _lock_path(path).is_file()

    recovered = record_target_position_intent(path, second)
    assert recovered.intents == (first, second)
    assert load_target_position_intent_journal(path) == recovered
    assert not _lock_path(path).exists()


def test_target_intent_journal_rejects_ambiguous_persisted_state(tmp_path: Path) -> None:
    path = tmp_path / "target-intents.jsonl"
    earlier = _intent(day=22, target_position=0.25)
    later = _intent(day=23, target_position=0.75)

    _write_private_journal(path, earlier.to_json_bytes() + earlier.to_json_bytes())
    with pytest.raises(ValueError, match="duplicate intent ID"):
        load_target_position_intent_journal(path)

    _write_private_journal(path, later.to_json_bytes() + earlier.to_json_bytes())
    with pytest.raises(ValueError, match="chronological ordering"):
        load_target_position_intent_journal(path)

    _write_private_journal(path, earlier.to_json_bytes().removesuffix(b"\n"))
    with pytest.raises(ValueError, match="newline-terminated"):
        load_target_position_intent_journal(path)

    _write_private_journal(path, earlier.to_json_bytes().replace(b"\n", b"\r\n"))
    with pytest.raises(ValueError, match="canonical encoding"):
        load_target_position_intent_journal(path)


def test_target_intent_journal_preserves_old_state_when_publication_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "target-intents.jsonl"
    first = _intent(day=22, target_position=0.25)
    second = _intent(day=23, target_position=0.75)
    record_target_position_intent(path, first)
    before = path.read_bytes()

    def fail_publish(*args: object, **kwargs: object) -> None:
        lock_path = _lock_path(path)
        assert lock_path.is_file()
        assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600
        raise OSError("simulated publication failure")

    monkeypatch.setattr(journal_module, "publish_payloads_atomically", fail_publish)
    with pytest.raises(OSError, match="simulated publication failure"):
        record_target_position_intent(path, second)

    assert path.read_bytes() == before
    assert load_target_position_intent_journal(path).intents == (first,)
    assert not _lock_path(path).exists()
