from __future__ import annotations

import copy
import gzip
import hashlib
import json
from pathlib import Path

import pytest

from gpt_quant.selector_evidence import canonical_json_bytes, load_training_artifact_bytes

_REPORT_ROOT = Path("reports/research/selector-protocol-v1")
_BTC = _REPORT_ROOT / "btc-usdt-training-evidence.json.gz"
_ETH = _REPORT_ROOT / "eth-usdt-training-evidence.json.gz"


def _read(path: Path) -> bytes:
    return gzip.decompress(path.read_bytes())


def _rehash(document: dict[str, object], *, table_index: int | None = None) -> bytes:
    if table_index is not None:
        table = document["tables"][table_index]
        body = {key: value for key, value in table.items() if key != "table_id"}
        table["table_id"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    body = {key: value for key, value in document.items() if key != "artifact_id"}
    document["artifact_id"] = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    return canonical_json_bytes(document) + b"\n"


@pytest.mark.parametrize("path", [_BTC, _ETH])
def test_real_selector_training_artifacts_reconstruct(path: Path) -> None:
    payload = _read(path)
    artifact = load_training_artifact_bytes(payload)

    assert artifact["family_id"] == "selector-protocol-v1"
    assert len(artifact["tables"]) == 12
    assert all(table["candidate_count"] == 27 for table in artifact["tables"])
    assert all(table["one_way_fee_bps"] == 5.0 for table in artifact["tables"])
    assert payload == canonical_json_bytes(artifact) + b"\n"


def test_score_tampering_is_rejected_even_after_rehash() -> None:
    artifact = copy.deepcopy(load_training_artifact_bytes(_read(_BTC)))
    artifact["tables"][0]["rows"][0]["training_score"] += 0.01

    with pytest.raises(ValueError, match="score"):
        load_training_artifact_bytes(_rehash(artifact, table_index=0))


def test_oos_result_field_is_rejected_even_after_rehash() -> None:
    artifact = copy.deepcopy(load_training_artifact_bytes(_read(_BTC)))
    artifact["tables"][0]["rows"][0]["next_fold_return"] = 0.01

    with pytest.raises(ValueError, match="row schema"):
        load_training_artifact_bytes(_rehash(artifact, table_index=0))


def test_first_oos_position_must_be_sourced_from_training_close() -> None:
    artifact = copy.deepcopy(load_training_artifact_bytes(_read(_BTC)))
    table = artifact["tables"][0]
    table["rows"][0]["first_causal_oos_target_source_timestamp"] = table["test_start"]

    with pytest.raises(ValueError, match="training-window close"):
        load_training_artifact_bytes(_rehash(artifact, table_index=0))


def test_rank_history_tampering_is_rejected() -> None:
    artifact = copy.deepcopy(load_training_artifact_bytes(_read(_BTC)))
    artifact["tables"][1]["rows"][0]["shrunk_percentile_rank"] += 0.01

    with pytest.raises(ValueError, match="shrunk percentile"):
        load_training_artifact_bytes(_rehash(artifact, table_index=1))


def test_duplicate_json_fields_are_rejected() -> None:
    payload = _read(_BTC)
    duplicate = payload.replace(b'{"artifact_id":', b'{"artifact_id":"duplicate","artifact_id":', 1)

    with pytest.raises(ValueError, match="duplicate JSON field"):
        load_training_artifact_bytes(duplicate)


def test_noncanonical_json_is_rejected() -> None:
    artifact = json.loads(_read(_BTC).decode("utf-8"))
    payload = json.dumps(artifact, indent=2, sort_keys=True).encode("utf-8") + b"\n"

    with pytest.raises(ValueError, match="one canonical JSON line|noncanonical"):
        load_training_artifact_bytes(payload)
