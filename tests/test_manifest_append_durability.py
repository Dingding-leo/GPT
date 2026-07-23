from __future__ import annotations

import json
from pathlib import Path

import pytest

import gpt_quant.manifest_io as manifest_module
from gpt_quant.manifest_io import append_experiment_manifest
from gpt_quant.reproducibility import canonical_json_sha256, file_sha256

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _fixture_entry(
    recorded_at_utc: str = "2026-07-21T15:01:16.374294+00:00",
) -> dict[str, object]:
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    experiment_evidence: dict[str, object] = {
        "schema_version": 1,
        "code_commit": "a" * 40,
        "config_sha256": canonical_json_sha256(
            {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"}
        ),
        "data_sha256": {
            "normalized_csv": file_sha256(_CANDLES),
            "raw_pages": file_sha256(_RAW),
        },
        "instrument_id": metadata["instrument_id"],
        "bar": metadata["bar"],
        "candidate_count": 27,
        "result_classification": "fixture-only durability test; no performance claim",
    }
    experiment_id = f"exp-{canonical_json_sha256(experiment_evidence)[:24]}"
    run_evidence = {
        "experiment_id": experiment_id,
        "recorded_at_utc": recorded_at_utc,
        "artifact_sha256": {"fixture_metadata": file_sha256(_METADATA)},
    }
    return {
        **experiment_evidence,
        **run_evidence,
        "run_id": f"run-{canonical_json_sha256(run_evidence)[:24]}",
    }


def test_manifest_replacement_fsyncs_parent_directory_for_each_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "nested" / "experiment-manifest.jsonl"
    first_entry = _fixture_entry()
    second_entry = _fixture_entry("2026-07-21T15:02:16.374294+00:00")
    fsynced_directories: list[Path] = []
    original_fsync_directory = manifest_module._fsync_directory

    def recording_fsync_directory(directory: Path) -> None:
        fsynced_directories.append(directory)
        original_fsync_directory(directory)

    monkeypatch.setattr(manifest_module, "_fsync_directory", recording_fsync_directory)

    path, appended = append_experiment_manifest(manifest, first_entry)

    assert path == manifest
    assert appended is True
    assert fsynced_directories == [manifest.parent]

    _, appended_again = append_experiment_manifest(manifest, first_entry)

    assert appended_again is False
    assert fsynced_directories == [manifest.parent]

    _, appended_second = append_experiment_manifest(manifest, second_entry)

    assert appended_second is True
    assert fsynced_directories == [manifest.parent, manifest.parent]


def test_failed_manifest_replacement_preserves_existing_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "experiment-manifest.jsonl"
    append_experiment_manifest(manifest, _fixture_entry())
    original_bytes = manifest.read_bytes()

    def failed_replace(_: Path, __: Path) -> None:
        raise OSError("simulated atomic replacement failure")

    monkeypatch.setattr(manifest_module.os, "replace", failed_replace)

    with pytest.raises(OSError, match="simulated atomic replacement failure"):
        append_experiment_manifest(
            manifest,
            _fixture_entry("2026-07-21T15:02:16.374294+00:00"),
        )

    assert manifest.read_bytes() == original_bytes
    assert list(tmp_path.glob(".experiment-manifest.jsonl.tmp-*")) == []
