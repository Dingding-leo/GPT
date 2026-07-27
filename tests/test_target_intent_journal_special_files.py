from __future__ import annotations

import os
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


def _intent() -> TargetPositionIntent:
    signal_open = datetime(2026, 7, 21, tzinfo=UTC)
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


def _install_nonblocking_open_guard(
    monkeypatch: pytest.MonkeyPatch,
    journal_path: Path,
) -> None:
    real_open = os.open

    def guarded_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is None and os.fspath(path) == os.fspath(journal_path):
            assert flags & os.O_NONBLOCK, "journal paths must be opened nonblocking"
        if dir_fd is None:
            return real_open(path, flags, mode)
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(journal_module.os, "open", guarded_open)


def _make_private_fifo(path: Path) -> None:
    os.mkfifo(path, 0o600)
    path.chmod(0o600)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO regression requires POSIX")
def test_fifo_journal_paths_fail_closed_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_path = tmp_path / "load-target-intents.jsonl"
    _make_private_fifo(load_path)
    _install_nonblocking_open_guard(monkeypatch, load_path)
    with pytest.raises(ValueError, match="regular single-link file"):
        load_target_position_intent_journal(load_path)

    monkeypatch.undo()
    record_path = tmp_path / "record-target-intents.jsonl"
    _make_private_fifo(record_path)
    _install_nonblocking_open_guard(monkeypatch, record_path)
    with pytest.raises(ValueError, match="regular single-link file"):
        record_target_position_intent(record_path, _intent())
    assert not (tmp_path / f".{record_path.name}.lock").exists()

    monkeypatch.undo()
    initialize_path = tmp_path / "initialize-target-intents.jsonl"
    _make_private_fifo(initialize_path)
    decision_directory = tmp_path / "new-paper-decisions"
    _install_nonblocking_open_guard(monkeypatch, initialize_path)
    with pytest.raises(ValueError, match="regular single-link file"):
        initialize_paper_order_decision_store(initialize_path, decision_directory)
    assert not decision_directory.exists()
    assert not (tmp_path / store_module._claim_name(decision_directory)).exists()

    monkeypatch.undo()
    replay_path = tmp_path / "replay-target-intents.jsonl"
    record_target_position_intent(replay_path, _intent())
    replay_directory = tmp_path / "paper-decisions"
    initialize_paper_order_decision_store(replay_path, replay_directory)
    replay_path.unlink()
    _make_private_fifo(replay_path)
    _install_nonblocking_open_guard(monkeypatch, replay_path)
    with pytest.raises(ValueError, match="regular single-link file"):
        store_module.replay_paper_order_decision_store(replay_path, replay_directory)
