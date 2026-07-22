from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from gpt_quant.reproducibility import build_experiment_manifest_entry, file_sha256

_REPOSITORY_ROOT = Path(__file__).parents[1]
_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _manifest_entry() -> dict[str, object]:
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    return build_experiment_manifest_entry(
        effective_config={
            "data": {
                "provider": metadata["provider"],
                "instrument_id": metadata["instrument_id"],
                "bar": metadata["bar"],
            }
        },
        data_hashes={
            "normalized_csv": file_sha256(_CANDLES),
            "raw_pages": file_sha256(_RAW),
        },
        data_paths={"normalized_csv": _CANDLES, "raw_pages": _RAW},
        artifact_paths={"fixture_metadata": _METADATA},
        candidate_count=27,
        result_classification="fixture-only CLI test; no performance claim",
        instrument_id=str(metadata["instrument_id"]),
        bar=str(metadata["bar"]),
        code_commit="c" * 40,
        recorded_at_utc="2026-07-21T15:01:16.374294+00:00",
    )


def _write_manifest(path: Path, entry: dict[str, object]) -> None:
    path.write_text(
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _parse_cli_output(output: str) -> dict[str, str]:
    return dict(line.split("=", maxsplit=1) for line in output.splitlines())


def test_registry_cli_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    manifest = tmp_path / "experiment-manifest.jsonl"
    registry = tmp_path / "experiment-registry.jsonl"
    _write_manifest(manifest, _manifest_entry())
    command = [
        sys.executable,
        str(_REPOSITORY_ROOT / "scripts" / "update_experiment_registry.py"),
        "--registry",
        str(registry),
        "--manifest",
        str(manifest),
    ]

    first = subprocess.run(
        command,
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    first_bytes = registry.read_bytes()
    second = subprocess.run(
        command,
        cwd=_REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    first_result = _parse_cli_output(first.stdout)
    second_result = _parse_cli_output(second.stdout)
    assert first_result["existing_runs"] == "0"
    assert first_result["appended_runs"] == "1"
    assert first_result["skipped_runs"] == "0"
    assert first_result["total_runs"] == "1"
    assert second_result["existing_runs"] == "1"
    assert second_result["appended_runs"] == "0"
    assert second_result["skipped_runs"] == "1"
    assert second_result["total_runs"] == "1"
    assert registry.read_bytes() == first_bytes
    assert first_result["registry_sha256"] == file_sha256(registry)
    assert second_result["registry_sha256"] == first_result["registry_sha256"]
