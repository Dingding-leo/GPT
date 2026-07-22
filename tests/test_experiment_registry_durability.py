from __future__ import annotations

import json
from pathlib import Path

import pytest

import gpt_quant.experiment_registry as registry_module
from gpt_quant.experiment_registry import merge_experiment_manifests
from gpt_quant.reproducibility import canonical_json_sha256, file_sha256

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _fixture_entry() -> dict[str, object]:
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
        "recorded_at_utc": "2026-07-21T15:01:16.374294+00:00",
        "artifact_sha256": {"fixture_metadata": file_sha256(_METADATA)},
    }
    return {
        **experiment_evidence,
        **run_evidence,
        "run_id": f"run-{canonical_json_sha256(run_evidence)[:24]}",
    }


def test_atomic_registry_replace_fsyncs_parent_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "manifest.jsonl"
    registry = tmp_path / "registry.jsonl"
    entry = _fixture_entry()
    manifest.write_text(
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )

    events: list[tuple[str, Path]] = []
    original_replace = registry_module.os.replace
    original_fsync_directory = registry_module._fsync_directory

    def recording_replace(source: str | Path, destination: str | Path) -> None:
        original_replace(source, destination)
        events.append(("replace", Path(destination)))

    def recording_fsync_directory(directory: Path) -> None:
        events.append(("fsync_directory", directory))
        original_fsync_directory(directory)

    monkeypatch.setattr(registry_module.os, "replace", recording_replace)
    monkeypatch.setattr(registry_module, "_fsync_directory", recording_fsync_directory)

    result = merge_experiment_manifests(registry, [manifest])

    assert result.appended_runs == 1
    assert events == [("replace", registry), ("fsync_directory", tmp_path)]
