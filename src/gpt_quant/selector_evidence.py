from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from . import _selector_evidence_core as _core

SCHEMA_VERSION = _core.SCHEMA_VERSION
CANDIDATE_COUNT = _core.CANDIDATE_COUNT
FOLD_COUNT = _core.FOLD_COUNT
SELECTION_BARS = _core.SELECTION_BARS
TEST_BARS = _core.TEST_BARS
BAR_DELTA = _core.BAR_DELTA
FAMILY_ID = _core.FAMILY_ID
DEVELOPMENT_MARKETS = _core.DEVELOPMENT_MARKETS
MOMENTUM_GRID = _core.MOMENTUM_GRID
REVERSAL_GRID = _core.REVERSAL_GRID
TREND_WEIGHT_GRID = _core.TREND_WEIGHT_GRID
SCORE_TIE_BREAK = _core.SCORE_TIE_BREAK
S2_GEOMETRY = _core.S2_GEOMETRY
METRICS = _core.METRICS
CANDIDATE_INPUT_KEYS = _core.CANDIDATE_INPUT_KEYS
FORBIDDEN_FIELDS = _core.FORBIDDEN_FIELDS
FEE = _core.FEE
HASH_KEYS = _core.HASH_KEYS
RECORD_KEYS = _core.RECORD_KEYS
TABLE_KEYS = _core.TABLE_KEYS
FROZEN_CANDIDATE_CONFIGS = _core.FROZEN_CANDIDATE_CONFIGS
canonical_json_bytes = _core.canonical_json_bytes

FROZEN_SELECTION_START = datetime(2021, 7, 24, tzinfo=UTC)


def _frozen_fold_window(fold: int) -> tuple[datetime, datetime, datetime, datetime]:
    selection_start = FROZEN_SELECTION_START + BAR_DELTA * TEST_BARS * (fold - 1)
    selection_end = selection_start + BAR_DELTA * (SELECTION_BARS - 1)
    test_start = selection_end + BAR_DELTA
    test_end = test_start + BAR_DELTA * (TEST_BARS - 1)
    return selection_start, selection_end, test_start, test_end


def _parsed_window(payload: Mapping[str, Any]) -> tuple[datetime, datetime, datetime, datetime]:
    keys = ("selection_start", "selection_end", "test_start", "test_end")
    parsed = [datetime.fromisoformat(str(payload[key]).replace("Z", "+00:00")) for key in keys]
    return parsed[0], parsed[1], parsed[2], parsed[3]


def _validate_frozen_fold_anchor(payload: Mapping[str, Any]) -> None:
    fold = int(payload["fold"])
    if _parsed_window(payload) != _frozen_fold_window(fold):
        raise ValueError("selector evidence windows do not match the frozen canonical fold")


def build_training_candidate_table(**kwargs: Any) -> dict[str, Any]:
    payload = _core.build_training_candidate_table(**kwargs)
    _validate_frozen_fold_anchor(payload)
    return payload


def reconstruct_training_candidate_table(raw: bytes) -> dict[str, Any]:
    payload = _core.reconstruct_training_candidate_table(raw)
    _validate_frozen_fold_anchor(payload)
    return payload


def serialize_training_candidate_table(payload: Mapping[str, Any]) -> bytes:
    raw = canonical_json_bytes(payload)
    reconstruct_training_candidate_table(raw)
    return raw


def validate_training_candidate_table_sequence(
    tables: Sequence[Mapping[str, Any]],
    *,
    require_complete: bool = True,
) -> None:
    validated = [
        reconstruct_training_candidate_table(canonical_json_bytes(table)) for table in tables
    ]
    _core.validate_training_candidate_table_sequence(
        validated,
        require_complete=require_complete,
    )
