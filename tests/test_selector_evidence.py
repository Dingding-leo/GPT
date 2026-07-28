from __future__ import annotations

# ruff: noqa: I001

import hashlib
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

import selector_evidence_cases as _cases
from gpt_quant.selector_evidence import (
    canonical_json_bytes,
    reconstruct_training_candidate_table,
    validate_training_candidate_table_sequence,
)

_cases.ORIGIN = datetime(2021, 7, 24, tzinfo=UTC)
_REPLACED_SEQUENCE_TEST = "test_sequence_reconstructs_all_folds_and_rejects_protocol_drift"
for _name in dir(_cases):
    if _name.startswith("test_") and _name != _REPLACED_SEQUENCE_TEST:
        globals()[_name] = getattr(_cases, _name)


def test_rejects_uniform_shift_of_the_complete_canonical_window() -> None:
    payload = _cases._build()
    body = deepcopy(payload)
    body.pop("table_id")
    for key in ("selection_start", "selection_end", "test_start", "test_end"):
        shifted = datetime.fromisoformat(body[key]) + timedelta(hours=1)
        body[key] = shifted.isoformat()
    body["table_id"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()

    with pytest.raises(ValueError, match="frozen canonical fold"):
        reconstruct_training_candidate_table(canonical_json_bytes(body))


def test_sequence_reconstructs_all_folds_and_rejects_protocol_drift() -> None:
    tables = _cases._sequence()
    validate_training_candidate_table_sequence(tables)

    with pytest.raises(ValueError, match="all 12 folds"):
        validate_training_candidate_table_sequence(tables[:2])
    validate_training_candidate_table_sequence(tables[:2], require_complete=False)

    bad_hash = deepcopy(tables[:2])
    bad_hash[1]["hashes"]["code_sha256"] = "2" * 64
    bad_hash[1] = reconstruct_training_candidate_table(_cases._rehash(bad_hash[1]))
    with pytest.raises(ValueError, match="hashes changed"):
        validate_training_candidate_table_sequence(bad_hash, require_complete=False)

    bad_time = deepcopy(tables[1])
    for key in ("selection_start", "selection_end", "test_start", "test_end"):
        shifted = datetime.fromisoformat(bad_time[key]) + timedelta(hours=1)
        bad_time[key] = shifted.isoformat()
    with pytest.raises(ValueError, match="frozen canonical fold"):
        reconstruct_training_candidate_table(_cases._rehash(bad_time))
