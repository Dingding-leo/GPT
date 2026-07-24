from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest

from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.execution_quote_binding_journal import (
    load_execution_quote_binding_journal,
    record_execution_quote_binding,
)
from test_execution_quote_binding_journal import _sources


@contextmanager
def _umask(value: int):
    previous = os.umask(value)
    try:
        yield
    finally:
        os.umask(previous)


def _record(tmp_path: Path, path: Path):
    intent, quote, intent_journal, quote_store = _sources(tmp_path)
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=quote.received_at_utc + timedelta(milliseconds=1),
        maximum_age_ms=250,
    )
    journal = record_execution_quote_binding(
        path,
        binding,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )
    return journal, intent_journal, quote_store


def test_binding_journal_uses_mode_0600_under_permissive_umask(tmp_path: Path) -> None:
    path = tmp_path / "bindings.jsonl"
    with _umask(0):
        journal, intent_journal, quote_store = _record(tmp_path, path)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (
        load_execution_quote_binding_journal(
            path,
            intent_journal=intent_journal,
            quote_store=quote_store,
        )
        == journal
    )


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "fifo"])
def test_binding_journal_rejects_aliased_or_blocking_replay_paths(
    tmp_path: Path,
    kind: str,
) -> None:
    path = tmp_path / "bindings.jsonl"
    _, intent_journal, quote_store = _record(tmp_path, path)
    alias = tmp_path / f"bindings-{kind}.jsonl"
    if kind == "symlink":
        alias.symlink_to(path.name)
    elif kind == "hardlink":
        os.link(path, alias)
    else:
        os.mkfifo(alias, 0o600)

    with pytest.raises(ValueError, match="private regular file|regular single-link"):
        load_execution_quote_binding_journal(
            alias,
            intent_journal=intent_journal,
            quote_store=quote_store,
        )


def test_binding_journal_rejects_insecure_mode_before_replay(tmp_path: Path) -> None:
    path = tmp_path / "bindings.jsonl"
    _, intent_journal, quote_store = _record(tmp_path, path)
    path.chmod(0o640)

    with pytest.raises(ValueError, match="mode 0600"):
        load_execution_quote_binding_journal(
            path,
            intent_journal=intent_journal,
            quote_store=quote_store,
        )


def test_binding_journal_rejects_writable_state_directory(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o777)
    path = state / "bindings.jsonl"
    intent, quote, intent_journal, quote_store = _sources(tmp_path)
    binding = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=quote.received_at_utc + timedelta(milliseconds=1),
        maximum_age_ms=250,
    )

    with pytest.raises(ValueError, match="must not be group/world-writable"):
        record_execution_quote_binding(
            path,
            binding,
            intent_journal=intent_journal,
            quote_store=quote_store,
        )
