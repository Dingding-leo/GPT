from __future__ import annotations

import json
from pathlib import Path

import pytest

from gpt_quant.reproducibility import (
    append_experiment_manifest,
    build_experiment_manifest_entry,
    file_sha256,
)

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _entry() -> dict[str, object]:
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    return build_experiment_manifest_entry(
        effective_config={
            "data": {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"},
            "search": {"candidate_count": 27},
        },
        data_hashes={
            "normalized_csv": str(metadata["fixture_normalized_csv_sha256"]),
            "raw_pages": str(metadata["fixture_raw_json_sha256"]),
        },
        data_paths={"normalized_csv": _CANDLES, "raw_pages": _RAW},
        artifact_paths={"fixture_metadata": _METADATA},
        candidate_count=27,
        result_classification="fixture-only legacy append validation; no performance claim",
        instrument_id="BTC-USDT",
        bar="1Dutc",
        code_commit="c" * 40,
        recorded_at_utc="2026-07-21T15:01:16.374294+00:00",
    )


def test_legacy_manifest_append_rejects_tampered_evidence_before_creating_file(
    tmp_path: Path,
) -> None:
    entry = _entry()
    entry["candidate_count"] = 28
    manifest = tmp_path / "experiment-manifest.jsonl"

    with pytest.raises(ValueError, match="experiment_id does not match"):
        append_experiment_manifest(manifest, entry)

    assert not manifest.exists()


def test_legacy_manifest_append_rejects_noncanonical_existing_evidence(tmp_path: Path) -> None:
    entry = _entry()
    manifest = tmp_path / "experiment-manifest.jsonl"
    manifest.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")
    before = file_sha256(manifest)

    with pytest.raises(ValueError, match="not canonical JSONL"):
        append_experiment_manifest(manifest, entry)

    assert file_sha256(manifest) == before
