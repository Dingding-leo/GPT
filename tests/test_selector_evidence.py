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
)

_cases.ORIGIN = datetime(2021, 7, 24, tzinfo=UTC)
for _name in dir(_cases):
    if _name.startswith("test_"):
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
