from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from gpt_quant.reproducibility import (
    append_experiment_manifest,
    build_experiment_manifest_entry,
    canonical_json_sha256,
    file_sha256,
)

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _fixture_metadata() -> dict[str, object]:
    return json.loads(_METADATA.read_text(encoding="utf-8"))


def _real_data_hashes() -> dict[str, str]:
    metadata = _fixture_metadata()
    return {
        "normalized_csv": str(metadata["fixture_normalized_csv_sha256"]),
        "raw_pages": str(metadata["fixture_raw_json_sha256"]),
    }


def _real_data_paths() -> dict[str, Path]:
    return {"normalized_csv": _CANDLES, "raw_pages": _RAW}


def test_real_okx_fixture_has_hash_verified_provenance() -> None:
    metadata = _fixture_metadata()

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["observations"] == 5
    assert metadata["source_workflow_run_id"] == 29841895366
    assert metadata["source_artifact_id"] == 8499721759
    assert file_sha256(_CANDLES) == metadata["fixture_normalized_csv_sha256"]
    assert file_sha256(_RAW) == metadata["fixture_raw_json_sha256"]


def test_canonical_json_hash_is_independent_of_mapping_order() -> None:
    left = {"b": [2, 1], "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "b": [2, 1]}

    assert canonical_json_sha256(left) == canonical_json_sha256(right)


def test_manifest_entry_records_config_data_and_artifact_hashes() -> None:
    timestamp = "2026-07-21T15:01:16.374294+00:00"

    entry = build_experiment_manifest_entry(
        effective_config={
            "data": {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"},
            "search": {"candidate_count": 27},
        },
        data_hashes=_real_data_hashes(),
        data_paths=_real_data_paths(),
        artifact_paths={"fixture_metadata": _METADATA},
        candidate_count=27,
        result_classification="fixture-only provenance test; no performance claim",
        instrument_id="BTC-USDT",
        bar="1Dutc",
        code_commit="c" * 40,
        recorded_at_utc=timestamp,
    )

    assert entry["code_commit"] == "c" * 40
    assert entry["config_sha256"] == canonical_json_sha256(
        {
            "data": {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"},
            "search": {"candidate_count": 27},
        }
    )
    assert entry["data_sha256"] == _real_data_hashes()
    assert entry["artifact_sha256"] == {"fixture_metadata": file_sha256(_METADATA)}
    assert entry["candidate_count"] == 27
    assert entry["experiment_id"].startswith("exp-")
    assert entry["run_id"].startswith("run-")


def test_manifest_entry_rejects_data_hash_mismatch(tmp_path) -> None:
    corrupted = tmp_path / "candles.csv"
    shutil.copyfile(_CANDLES, corrupted)
    corrupted.write_text(
        corrupted.read_text(encoding="utf-8") + "# structural corruption for fail-closed test\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="data hash mismatch for 'normalized_csv'"):
        build_experiment_manifest_entry(
            effective_config={"data": {"provider": "OKX"}},
            data_hashes={"normalized_csv": _real_data_hashes()["normalized_csv"]},
            data_paths={"normalized_csv": corrupted},
            artifact_paths={"fixture_metadata": _METADATA},
            candidate_count=1,
            result_classification="fixture-only rejection test; no performance claim",
            instrument_id="BTC-USDT",
            bar="1Dutc",
            code_commit="e" * 40,
            recorded_at_utc="2026-07-21T15:01:16.374294+00:00",
        )


def test_manifest_entry_rejects_incomplete_data_path_mapping() -> None:
    with pytest.raises(ValueError, match="data_paths keys must exactly match"):
        build_experiment_manifest_entry(
            effective_config={"data": {"provider": "OKX"}},
            data_hashes=_real_data_hashes(),
            data_paths={"normalized_csv": _CANDLES},
            artifact_paths={"fixture_metadata": _METADATA},
            candidate_count=1,
            result_classification="fixture-only rejection test; no performance claim",
            instrument_id="BTC-USDT",
            bar="1Dutc",
            code_commit="e" * 40,
            recorded_at_utc="2026-07-21T15:01:16.374294+00:00",
        )


def test_manifest_append_is_canonical_and_idempotent(tmp_path) -> None:
    entry = build_experiment_manifest_entry(
        effective_config={"data": {"provider": "OKX"}},
        data_hashes=_real_data_hashes(),
        data_paths=_real_data_paths(),
        artifact_paths={"fixture_metadata": _METADATA},
        candidate_count=1,
        result_classification="fixture-only append test; no performance claim",
        instrument_id="BTC-USDT",
        bar="1Dutc",
        code_commit="e" * 40,
        recorded_at_utc="2026-07-21T15:01:16.374294+00:00",
    )
    manifest = tmp_path / "experiment-manifest.jsonl"

    path, appended = append_experiment_manifest(manifest, entry)
    _, appended_again = append_experiment_manifest(manifest, entry)

    assert path == manifest
    assert appended is True
    assert appended_again is False
    lines = manifest.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == entry
    assert lines[0] == json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
