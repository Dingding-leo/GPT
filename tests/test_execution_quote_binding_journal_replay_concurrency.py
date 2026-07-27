from __future__ import annotations

import threading
from datetime import timedelta
from pathlib import Path

import pytest
from test_execution_quote_binding_journal import _sources

import gpt_quant.execution_quote_binding_journal as binding_journal_module
from gpt_quant.execution_quote_binding import bind_execution_quote
from gpt_quant.execution_quote_binding_journal import (
    load_execution_quote_binding_journal,
    record_execution_quote_binding,
)


def test_binding_replay_blocks_concurrent_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "state" / "bindings.jsonl"
    path.parent.mkdir(mode=0o700)
    intent, quote, intent_journal, quote_store = _sources(tmp_path)
    first = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=quote.received_at_utc + timedelta(milliseconds=1),
        maximum_age_ms=250,
    )
    later = bind_execution_quote(
        intent,
        quote,
        decision_at_utc=quote.received_at_utc + timedelta(milliseconds=2),
        maximum_age_ms=250,
    )
    initial = record_execution_quote_binding(
        path,
        first,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )

    replay_read = threading.Event()
    release_replay = threading.Event()
    original_read = binding_journal_module._read_private_journal

    def pause_after_replay_read(directory_descriptor: int, name: str) -> bytes:
        payload = original_read(directory_descriptor, name)
        if threading.current_thread().name == "binding-journal-replay" and name == path.name:
            replay_read.set()
            assert release_replay.wait(timeout=5)
        return payload

    monkeypatch.setattr(
        binding_journal_module,
        "_read_private_journal",
        pause_after_replay_read,
    )
    replay_result: dict[str, object] = {}
    replay_errors: list[Exception] = []

    def replay() -> None:
        try:
            replay_result["journal"] = load_execution_quote_binding_journal(
                path,
                intent_journal=intent_journal,
                quote_store=quote_store,
            )
        except Exception as exc:  # pragma: no cover - surfaced below
            replay_errors.append(exc)

    replay_thread = threading.Thread(target=replay, name="binding-journal-replay")
    replay_thread.start()
    assert replay_read.wait(timeout=5)

    with pytest.raises(RuntimeError, match="writer lock already exists"):
        record_execution_quote_binding(
            path,
            later,
            intent_journal=intent_journal,
            quote_store=quote_store,
        )
    assert path.read_bytes() == initial.to_bytes()

    release_replay.set()
    replay_thread.join(timeout=5)
    assert not replay_thread.is_alive()
    assert replay_errors == []
    assert replay_result["journal"] == initial
    assert not path.with_name(f".{path.name}.lock").exists()

    updated = record_execution_quote_binding(
        path,
        later,
        intent_journal=intent_journal,
        quote_store=quote_store,
    )
    assert updated.count == 2
    assert updated.bindings[-1] == later
