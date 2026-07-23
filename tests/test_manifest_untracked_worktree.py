from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from gpt_quant.reproducibility import build_experiment_manifest_entry

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository_with_tracked_source(tmp_path: Path) -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "reproducibility-test")
    _git(repository, "config", "user.email", "reproducibility@example.invalid")
    source = repository / "strategy.py"
    source.write_text("SIGNAL_SCALE = 1.0\n", encoding="utf-8")
    _git(repository, "add", source.name)
    _git(repository, "commit", "-m", "initial source")
    return repository


def _manifest_arguments(repository: Path) -> dict[str, object]:
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    return {
        "effective_config": {
            "data": {
                "provider": metadata["provider"],
                "instrument_id": metadata["instrument_id"],
                "bar": metadata["bar"],
            }
        },
        "data_hashes": {
            "normalized_csv": metadata["fixture_normalized_csv_sha256"],
            "raw_pages": metadata["fixture_raw_json_sha256"],
        },
        "artifact_paths": {"fixture_metadata": _METADATA},
        "candidate_count": 27,
        "result_classification": (
            "fixture-only untracked-worktree provenance validation; no performance claim"
        ),
        "instrument_id": str(metadata["instrument_id"]),
        "bar": str(metadata["bar"]),
        "repository_root": repository,
        "recorded_at_utc": "2026-07-23T06:30:00+00:00",
    }


@pytest.mark.parametrize(
    ("relative_path", "executable"),
    [
        ("scripts/local_override.py", False),
        ("config/local.json", False),
        (".github/workflows/local.yml", False),
        ("notes/audit.py", False),
        ("tools/local-runner", True),
    ],
)
def test_manifest_rejects_untracked_run_inputs_before_artifact_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    executable: bool,
) -> None:
    repository = _repository_with_tracked_source(tmp_path)
    candidate = repository / relative_path
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text("local override\n", encoding="utf-8")
    if executable:
        candidate.chmod(0o755)

    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    def _unexpected_hash(_: str | Path) -> str:
        pytest.fail("untracked run inputs must fail before market or artifact hashing")

    monkeypatch.setattr("gpt_quant.reproducibility.file_sha256", _unexpected_hash)

    with pytest.raises(RuntimeError, match="untracked executable or configuration files"):
        build_experiment_manifest_entry(**_manifest_arguments(repository))


def test_manifest_allows_untracked_generated_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository_with_tracked_source(tmp_path)
    report = repository / "reports" / "run-summary.json"
    report.parent.mkdir(parents=True)
    report.write_text('{"status":"generated"}\n', encoding="utf-8")

    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)

    entry = build_experiment_manifest_entry(**_manifest_arguments(repository))

    assert entry["code_commit"] == _git(repository, "rev-parse", "HEAD")
