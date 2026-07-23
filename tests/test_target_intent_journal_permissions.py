from __future__ import annotations

import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from gpt_quant.execution_intent import TargetPositionIntent
from gpt_quant.target_intent_journal import (
    load_target_position_intent_journal,
    record_target_position_intent,
)

_SOURCE_SHA256 = "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149"
_CONFIG_SHA256 = "a0340ca26a0c5e7d0d609ddf69bcb3e4e643a93ab009f27ee03e8ea322aed822"
_REVISION = "d09ae3003000d10c5b208428d0a92816069cda53"


def _intent(*, day: int = 22, target_position: float = 0.5) -> TargetPositionIntent:
    signal_open = datetime(2026, 7, day, tzinfo=UTC)
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
        decision_not_before_utc=signal_close + timedelta(seconds=3),
        expires_at_utc=signal_close + timedelta(days=1),
        target_position=target_position,
        minimum_position=0.0,
        maximum_position=1.0,
    )


def test_target_intent_journal_is_owner_only_with_permissive_umask(tmp_path: Path) -> None:
    path = tmp_path / "target-intents.jsonl"
    previous_umask = os.umask(0)
    try:
        journal = record_target_position_intent(path, _intent())
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_target_position_intent_journal(path) == journal


def test_target_intent_journal_rejects_group_readable_state(tmp_path: Path) -> None:
    path = tmp_path / "target-intents.jsonl"
    path.write_bytes(_intent().to_json_bytes())
    path.chmod(0o640)
    before = path.read_bytes()

    with pytest.raises(ValueError, match="owner-only mode 0600"):
        load_target_position_intent_journal(path)
    with pytest.raises(ValueError, match="owner-only mode 0600"):
        record_target_position_intent(path, _intent(day=23, target_position=0.75))

    assert path.read_bytes() == before
    assert not path.with_name(f".{path.name}.lock").exists()


def test_target_intent_journal_rejects_hardlinked_state(tmp_path: Path) -> None:
    path = tmp_path / "target-intents.jsonl"
    alias = tmp_path / "attacker-alias.jsonl"
    path.write_bytes(_intent().to_json_bytes())
    path.chmod(0o600)
    os.link(path, alias)

    with pytest.raises(ValueError, match="regular single-link file"):
        load_target_position_intent_journal(path)

    assert path.read_bytes() == alias.read_bytes()
    assert path.stat().st_nlink == 2


def test_target_intent_journal_rejects_symlink_state(tmp_path: Path) -> None:
    target = tmp_path / "attacker-controlled.jsonl"
    target.write_bytes(_intent().to_json_bytes())
    target.chmod(0o600)
    path = tmp_path / "target-intents.jsonl"
    path.symlink_to(target)

    with pytest.raises(ValueError, match="must not be a symbolic link"):
        load_target_position_intent_journal(path)

    assert target.read_bytes() == _intent().to_json_bytes()


def test_target_intent_journal_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is unavailable")

    path = tmp_path / "target-intents.jsonl"
    os.mkfifo(path, 0o600)

    with pytest.raises(ValueError, match="regular single-link file"):
        load_target_position_intent_journal(path)
