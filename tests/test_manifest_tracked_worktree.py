from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from gpt_quant.reproducibility import build_experiment_manifest_entry

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository_with_tracked_source(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "reproducibility-test")
    _git(repository, "config", "user.email", "reproducibility@example.invalid")
    source = repository / "strategy.py"
    source.write_text("SIGNAL_SCALE = 1.0\n", encoding="utf-8")
    _git(repository, "add", source.name)
    _git(repository, "commit", "-m", "initial source")
    return repository, source


@pytest.mark.parametrize("staged", [False, True])
def test_manifest_rejects_modified_tracked_checkout_before_artifact_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    staged: bool,
) -> None:
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    repository, source = _repository_with_tracked_source(tmp_path)
    source.write_text("SIGNAL_SCALE = 2.0\n", encoding="utf-8")
    if staged:
        _git(repository, "add", source.name)

    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    def _unexpected_hash(_: str | Path) -> str:
        pytest.fail("dirty tracked checkout must fail before market or artifact hashing")

    monkeypatch.setattr("gpt_quant.reproducibility.file_sha256", _unexpected_hash)

    with pytest.raises(RuntimeError, match="tracked worktree differs from HEAD"):
        build_experiment_manifest_entry(
            effective_config={
                "data": {
                    "provider": metadata["provider"],
                    "instrument_id": metadata["instrument_id"],
                    "bar": metadata["bar"],
                }
            },
            data_hashes={
                "normalized_csv": metadata["fixture_normalized_csv_sha256"],
                "raw_pages": metadata["fixture_raw_json_sha256"],
            },
            data_paths={"normalized_csv": _CANDLES, "raw_pages": _RAW},
            artifact_paths={"fixture_metadata": _METADATA},
            candidate_count=27,
            result_classification="fixture-only dirty-worktree rejection; no performance claim",
            instrument_id=str(metadata["instrument_id"]),
            bar=str(metadata["bar"]),
            repository_root=repository,
            recorded_at_utc="2026-07-23T05:11:00+00:00",
        )
