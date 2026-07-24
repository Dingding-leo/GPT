from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from gpt_quant.artifact_manifest import build_manifest, verify_manifest


def test_manifest_is_deterministic_and_verifies_from_download_root(tmp_path: Path) -> None:
    artifact = tmp_path / "workspace" / "reports" / "okx" / "1h" / "BTC-USDT"
    artifact.mkdir(parents=True)
    (artifact / "effective_config.json").write_text('{"bar":"1H"}\n', encoding="utf-8")
    (artifact / "snapshot").mkdir()
    (artifact / "snapshot" / "source.raw.json").write_bytes(b'{"code":"0"}\n')
    (artifact / "walk_forward.json").write_text('{"fee_bps":5}\n', encoding="utf-8")

    first_digest = build_manifest(artifact)
    first_manifest = (artifact / "artifact-manifest.sha256").read_text(encoding="utf-8")
    second_digest = build_manifest(artifact)

    assert second_digest == first_digest
    assert (artifact / "artifact-manifest.sha256").read_text(encoding="utf-8") == first_manifest
    manifest_paths = [line.split("  ", 1)[1] for line in first_manifest.splitlines()]
    assert manifest_paths == sorted(manifest_paths)
    assert manifest_paths == [
        "effective_config.json",
        "snapshot/source.raw.json",
        "walk_forward.json",
    ]
    assert all(not Path(path).is_absolute() and "reports/" not in path for path in manifest_paths)

    downloaded = tmp_path / "downloaded-artifact"
    shutil.copytree(artifact, downloaded)
    verify_manifest(downloaded)


def test_manifest_fails_closed_after_downloaded_file_is_tampered(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    report = artifact / "walk_forward.json"
    report.write_text('{"value":0.1}\n', encoding="utf-8")
    build_manifest(artifact)

    report.write_text('{"value":9.9}\n', encoding="utf-8")

    with pytest.raises(ValueError, match="digest mismatch"):
        verify_manifest(artifact)


def test_manifest_fails_closed_when_download_contains_unmanifested_file(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "walk_forward.json").write_text('{"value":0.1}\n', encoding="utf-8")
    build_manifest(artifact)

    unexpected = artifact / "nested" / "unmanifested-result.json"
    unexpected.parent.mkdir()
    unexpected.write_text('{"value":9.9}\n', encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"unmanifested files: nested/unmanifested-result\.json",
    ):
        verify_manifest(artifact)


def test_nested_manifest_named_file_is_bound_by_root_manifest(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact"
    nested = artifact / "nested"
    nested.mkdir(parents=True)
    (artifact / "walk_forward.json").write_text('{"value":0.1}\n', encoding="utf-8")
    (nested / "artifact-manifest.sha256").write_text("provider evidence\n", encoding="utf-8")

    build_manifest(artifact)

    manifest = (artifact / "artifact-manifest.sha256").read_text(encoding="utf-8")
    assert "nested/artifact-manifest.sha256" in manifest
    verify_manifest(artifact)


def test_manifest_rejects_hard_linked_external_evidence(tmp_path: Path) -> None:
    outside = tmp_path / "outside-walk-forward.json"
    outside.write_text('{"value":0.1}\n', encoding="utf-8")
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    linked = artifact / "walk_forward.json"
    try:
        os.link(outside, linked)
    except OSError as exc:
        pytest.skip(f"filesystem does not support hard-link regression: {exc}")

    assert linked.stat().st_ino == outside.stat().st_ino
    assert linked.stat().st_nlink == 2
    with pytest.raises(ValueError, match="must not be hard-linked"):
        build_manifest(artifact)
