from __future__ import annotations

import json
import os
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


def _canonical_entry_bytes(entry: dict[str, object]) -> bytes:
    return (
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


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


def test_manifest_append_rejects_symlink_output_directory_before_locking(
    tmp_path: Path,
) -> None:
    external_output = tmp_path / "operator-output"
    external_output.mkdir()
    sentinel = external_output / "operator-note.txt"
    sentinel.write_bytes(b"operator-owned\n")
    output = tmp_path / "reports"
    output.symlink_to(external_output, target_is_directory=True)
    manifest = output / "experiment-manifest.jsonl"

    with pytest.raises(ValueError, match="output directory must not be a symbolic link"):
        append_experiment_manifest(manifest, _fixture_entry())

    assert output.is_symlink()
    assert sentinel.read_bytes() == b"operator-owned\n"
    assert {path.name for path in external_output.iterdir()} == {"operator-note.txt"}


@pytest.mark.parametrize(
    ("link_kind", "expected_error"),
    [
        ("symlink", "manifest destination must not be a symbolic link"),
        ("hardlink", "manifest destination must not be a hard-linked file"),
    ],
)
def test_manifest_append_rejects_linked_destination_before_locking(
    tmp_path: Path,
    link_kind: str,
    expected_error: str,
) -> None:
    external_manifest = tmp_path / "operator-manifest.jsonl"
    external_manifest.write_bytes(_canonical_entry_bytes(_fixture_entry()))
    original_bytes = external_manifest.read_bytes()
    manifest = tmp_path / "experiment-manifest.jsonl"
    if link_kind == "symlink":
        manifest.symlink_to(external_manifest)
    else:
        os.link(external_manifest, manifest)

    with pytest.raises(ValueError, match=expected_error):
        append_experiment_manifest(
            manifest,
            _fixture_entry("2026-07-21T15:02:16.374294+00:00"),
        )

    assert external_manifest.read_bytes() == original_bytes
    if link_kind == "symlink":
        assert manifest.is_symlink()
    else:
        assert manifest.samefile(external_manifest)
        assert manifest.stat().st_nlink == 2
    assert not (tmp_path / ".experiment-manifest.jsonl.lock").exists()
    assert list(tmp_path.glob(".experiment-manifest.jsonl.tmp-*")) == []


@pytest.mark.parametrize(
    ("link_kind", "expected_error"),
    [
        ("symlink", "manifest lock must not be a symbolic link"),
        ("hardlink", "manifest lock must not be a hard-linked file"),
    ],
)
def test_manifest_append_rejects_linked_lock_before_mutation(
    tmp_path: Path,
    link_kind: str,
    expected_error: str,
) -> None:
    external_lock = tmp_path / "operator-lock"
    external_lock.write_bytes(b"operator-owned\n")
    original_bytes = external_lock.read_bytes()
    manifest = tmp_path / "experiment-manifest.jsonl"
    lock_path = tmp_path / ".experiment-manifest.jsonl.lock"
    if link_kind == "symlink":
        lock_path.symlink_to(external_lock)
    else:
        os.link(external_lock, lock_path)

    with pytest.raises(ValueError, match=expected_error):
        append_experiment_manifest(manifest, _fixture_entry())

    assert not manifest.exists()
    assert external_lock.read_bytes() == original_bytes
    if link_kind == "symlink":
        assert lock_path.is_symlink()
    else:
        assert lock_path.samefile(external_lock)
        assert lock_path.stat().st_nlink == 2
    assert list(tmp_path.glob(".experiment-manifest.jsonl.tmp-*")) == []
