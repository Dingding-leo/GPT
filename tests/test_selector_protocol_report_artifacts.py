from __future__ import annotations

import base64
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from gpt_quant.selector_evidence import reconstruct_training_candidate_table
from gpt_quant.selector_protocol import validate_canonical_training_candidate_table_sequence

REPORT_ROOT = Path("reports/research/selector-protocol-v1")
FAMILY_ID = "selector-protocol-v1|1h|frozen-27-grid|6-policies|btc-eth-development"
EXPECTED_TRAINING_HASHES = {
    "BTC-USDT": {
        "compressed": "ce5f17f2e67d508bc312b6b3b0ffcce1e323309aad8f3cb9b236a8047300e822",
        "payload": "43dd6400d55a72c08fd63b545ff4f77c18af245e75e3952453ddeef4f3572348",
    },
    "ETH-USDT": {
        "compressed": "b1f6e5539970c7ae6f916d55cd7505377eade5b5a364b051efda777040469bf2",
        "payload": "46a7ba551162498fc1b69a13f85ad0ad4c17d2c9f9413923c89b96dd10129155",
    },
}
EXPECTED_RESULT_PAYLOAD_SHA256 = (
    "8ffb4b2e267fa80379e01aade5d68f1ef0395cb876d98d4eb4463eddbe1eeb71"
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_object(raw: bytes) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    parsed = json.loads(raw, object_pairs_hook=reject_duplicates)
    if not isinstance(parsed, dict):
        raise ValueError("selector result must be a JSON object")
    return parsed


def _decode_report(path: Path) -> tuple[bytes, bytes]:
    encoded = path.read_bytes().strip()
    assert b"ELLIPSIZATION" not in encoded
    compressed = base64.b64decode(encoded, validate=True)
    return compressed, gzip.decompress(compressed)


def test_training_evidence_is_complete_reconstructable_and_calendar_bound() -> None:
    final_ids: dict[str, str] = {}
    for market, expected in EXPECTED_TRAINING_HASHES.items():
        path = REPORT_ROOT / f"{market}.training-evidence.jsonl.gz.b64"
        compressed, payload = _decode_report(path)
        assert _sha256(compressed) == expected["compressed"]
        assert _sha256(payload) == expected["payload"]

        lines = payload.splitlines(keepends=True)
        assert len(lines) == 12
        tables = [reconstruct_training_candidate_table(line) for line in lines]
        validate_canonical_training_candidate_table_sequence(tables)
        assert [table["fold"] for table in tables] == list(range(1, 13))
        assert {table["market"] for table in tables} == {market}
        final_ids[market] = str(tables[-1]["table_id"])

    assert len(set(final_ids.values())) == 2


def test_official_result_is_strict_json_with_published_hash_and_contract() -> None:
    path = REPORT_ROOT / "selector-protocol-v1-oos-comparison.json.gz.b64"
    _, payload = _decode_report(path)
    assert _sha256(payload) == EXPECTED_RESULT_PAYLOAD_SHA256

    result = _strict_object(payload)
    assert result["family_id"] == FAMILY_ID
    assert result["bar"] == "1H"
    assert result["modeled_fee_one_way_bps"] == 5
    assert result["candidate_count"] == 27
    assert result["policy_fold_evaluations"] == 144
    assert result["new_untouched_evidence_consumed"] is False
