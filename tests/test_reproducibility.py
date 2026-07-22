from __future__ import annotations

import json
import shutil
import subprocess
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


def _manifest_entry(**overrides: object) -> dict[str, object]:
    arguments: dict[str, object] = {
        "effective_config": {
            "data": {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"},
            "search": {"candidate_count": 27},
        },
        "data_hashes": _real_data_hashes(),
        "data_paths": _real_data_paths(),
        "artifact_paths": {"fixture_metadata": _METADATA},
        "candidate_count": 27,
        "result_classification": "fixture-only provenance test; no performance claim",
        "instrument_id": "BTC-USDT",
        "bar": "1Dutc",
        "code_commit": "c" * 40,
        "recorded_at_utc": "2026-07-21T15:01:16.374294+00:00",
    }
    arguments.update(overrides)
    return build_experiment_manifest_entry(**arguments)  # type: ignore[arg-type]


def _write_pull_request_event(path: Path, *, head: str, base: str) -> None:
    path.write_text(
        json.dumps(
            {
                "pull_request": {
                    "head": {"sha": head},
                    "base": {"sha": base},
                }
            }
        ),
        encoding="utf-8",
    )


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
    entry = _manifest_entry()

    assert entry["schema_version"] == 2
    assert entry["code_commit"] == "c" * 40
    assert entry["code_provenance"] == {"checkout_commit": "c" * 40}
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


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _build_shallow_merge_checkout(tmp_path: Path) -> tuple[Path, str, str, str, str]:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.name", "reproducibility-test")
    _git(source, "config", "user.email", "reproducibility@example.invalid")
    (source / "base.txt").write_text("base\n", encoding="utf-8")
    _git(source, "add", "base.txt")
    _git(source, "commit", "-m", "base")
    event_base = _git(source, "rev-parse", "HEAD")

    _git(source, "checkout", "-b", "feature")
    (source / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(source, "add", "feature.txt")
    _git(source, "commit", "-m", "feature")
    feature_head = _git(source, "rev-parse", "HEAD")

    _git(source, "checkout", "main")
    (source / "advanced-base.txt").write_text("advanced\n", encoding="utf-8")
    _git(source, "add", "advanced-base.txt")
    _git(source, "commit", "-m", "advance base")
    tested_base = _git(source, "rev-parse", "HEAD")
    _git(source, "merge", "--no-ff", "feature", "-m", "test merge")
    merge_commit = _git(source, "rev-parse", "HEAD")

    bare = tmp_path / "source.git"
    subprocess.run(
        ["git", "clone", "--bare", str(source), str(bare)],
        check=True,
        capture_output=True,
        text=True,
    )
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    _git(checkout, "init")
    _git(checkout, "remote", "add", "origin", bare.as_uri())
    _git(checkout, "fetch", "--depth=1", "origin", merge_commit)
    _git(checkout, "checkout", "FETCH_HEAD")
    return checkout, event_base, tested_base, feature_head, merge_commit


def test_pull_request_manifest_uses_tested_merge_base_not_stale_event_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout, event_base, tested_base, feature_head, merge_commit = _build_shallow_merge_checkout(
        tmp_path
    )
    event_path = tmp_path / "event.json"
    _write_pull_request_event(event_path, head=feature_head, base=event_base)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_SHA", merge_commit)

    entry = _manifest_entry(code_commit=None, repository_root=checkout)

    assert event_base != tested_base
    assert entry["code_commit"] == merge_commit
    assert entry["code_provenance"] == {
        "checkout_commit": merge_commit,
        "pull_request_head_commit": feature_head,
        "pull_request_base_commit": tested_base,
    }


def test_pull_request_manifest_rejects_merge_head_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_path = tmp_path / "event.json"
    _write_pull_request_event(event_path, head="a" * 40, base="b" * 40)
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)
    monkeypatch.setattr(
        "gpt_quant.reproducibility._resolve_pull_request_merge_parents",
        lambda _: ("b" * 40, "d" * 40),
    )

    with pytest.raises(RuntimeError, match="merge head does not match"):
        _manifest_entry(
            code_commit=None,
            repository_root=tmp_path / "missing-checkout",
        )


def test_pull_request_manifest_fails_closed_without_persistent_revisions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_path = tmp_path / "event.json"
    event_path.write_text(
        json.dumps({"pull_request": {"head": {"sha": "a" * 40}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_path))
    monkeypatch.setenv("GITHUB_SHA", "c" * 40)

    with pytest.raises(
        RuntimeError,
        match="unable to resolve pull-request head/base commits",
    ):
        _manifest_entry(
            code_commit=None,
            repository_root=tmp_path / "missing-checkout",
        )


def test_manifest_entry_rejects_data_hash_mismatch(tmp_path: Path) -> None:
    corrupted = tmp_path / "candles.csv"
    shutil.copyfile(_CANDLES, corrupted)
    corrupted.write_text(
        corrupted.read_text(encoding="utf-8") + "# structural corruption for fail-closed test\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="data hash mismatch for 'normalized_csv'"):
        _manifest_entry(
            effective_config={"data": {"provider": "OKX"}},
            data_hashes={"normalized_csv": _real_data_hashes()["normalized_csv"]},
            data_paths={"normalized_csv": corrupted},
            candidate_count=1,
            result_classification="fixture-only rejection test; no performance claim",
            code_commit="e" * 40,
        )


def test_manifest_entry_rejects_incomplete_data_path_mapping() -> None:
    with pytest.raises(ValueError, match="data_paths keys must exactly match"):
        _manifest_entry(
            effective_config={"data": {"provider": "OKX"}},
            data_paths={"normalized_csv": _CANDLES},
            candidate_count=1,
            result_classification="fixture-only rejection test; no performance claim",
            code_commit="e" * 40,
        )


def test_manifest_append_is_canonical_and_idempotent(tmp_path: Path) -> None:
    entry = _manifest_entry(
        effective_config={"data": {"provider": "OKX"}},
        candidate_count=1,
        result_classification="fixture-only append test; no performance claim",
        code_commit="e" * 40,
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
