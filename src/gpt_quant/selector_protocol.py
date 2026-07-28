from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from .selector_evidence import (
    BAR_DELTA,
    FOLD_COUNT,
    SELECTION_BARS,
    TEST_BARS,
    validate_training_candidate_table_sequence,
)

CANONICAL_FIRST_SELECTION_START = datetime(2021, 7, 24, tzinfo=UTC)


def canonical_fold_window(fold: int) -> tuple[datetime, datetime, datetime, datetime]:
    """Return the frozen BTC/ETH development window for one selector fold."""

    valid_fold = not isinstance(fold, bool) and isinstance(fold, int) and 1 <= fold <= FOLD_COUNT
    if not valid_fold:
        raise ValueError("fold must be an integer from 1 through 12")
    selection_start = CANONICAL_FIRST_SELECTION_START + BAR_DELTA * TEST_BARS * (fold - 1)
    selection_end = selection_start + BAR_DELTA * (SELECTION_BARS - 1)
    test_start = selection_end + BAR_DELTA
    test_end = test_start + BAR_DELTA * (TEST_BARS - 1)
    return selection_start, selection_end, test_start, test_end


def _utc_hour(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO-8601 UTC hour")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 UTC hour") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{label} must be an ISO-8601 UTC hour")
    if parsed.minute or parsed.second or parsed.microsecond:
        raise ValueError(f"{label} must be aligned to a complete UTC hour")
    return parsed


def validate_canonical_training_candidate_table_sequence(
    tables: Sequence[Mapping[str, Any]],
) -> None:
    """Reject a valid-looking sequence that substitutes another OOS calendar."""

    validate_training_candidate_table_sequence(tables, require_complete=True)
    for expected_fold, table in enumerate(tables, start=1):
        expected = canonical_fold_window(expected_fold)
        actual = (
            _utc_hour(table.get("selection_start"), "selection_start"),
            _utc_hour(table.get("selection_end"), "selection_end"),
            _utc_hour(table.get("test_start"), "test_start"),
            _utc_hour(table.get("test_end"), "test_end"),
        )
        if actual != expected:
            raise ValueError("selector evidence does not use the frozen development calendar")
