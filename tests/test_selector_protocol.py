from __future__ import annotations

from datetime import timedelta

import pytest

from gpt_quant import selector_protocol


def _tables(shift: timedelta = timedelta(0)) -> list[dict[str, object]]:
    tables: list[dict[str, object]] = []
    for fold in range(1, selector_protocol.FOLD_COUNT + 1):
        window = selector_protocol.canonical_fold_window(fold)
        tables.append(
            {
                "selection_start": (window[0] + shift).isoformat(),
                "selection_end": (window[1] + shift).isoformat(),
                "test_start": (window[2] + shift).isoformat(),
                "test_end": (window[3] + shift).isoformat(),
            }
        )
    return tables


def test_canonical_selector_calendar_is_accepted(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        selector_protocol,
        "validate_training_candidate_table_sequence",
        lambda tables, require_complete: None,
    )
    selector_protocol.validate_canonical_training_candidate_table_sequence(_tables())


def test_globally_shifted_selector_calendar_is_rejected(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        selector_protocol,
        "validate_training_candidate_table_sequence",
        lambda tables, require_complete: None,
    )
    with pytest.raises(ValueError, match="frozen development calendar"):
        selector_protocol.validate_canonical_training_candidate_table_sequence(
            _tables(timedelta(hours=1))
        )
