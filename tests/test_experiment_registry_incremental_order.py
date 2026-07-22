from __future__ import annotations

import json
from pathlib import Path

from gpt_quant.experiment_registry import (
    load_manifest_entries,
    merge_experiment_manifests,
)
from gpt_quant.reproducibility import build_experiment_manifest_entry, file_sha256

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _entry(recorded_at_utc: str) -> dict[str, object]:
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    return build_experiment_manifest_entry(
        effective_config={
            "data": {
                "provider": "OKX",
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
        result_classification="fixture-only registry ordering test; no performance claim",
        instrument_id=metadata["instrument_id"],
        bar=metadata["bar"],
        code_provenance={
            "checkout_commit": "c" * 40,
            "pull_request_head_commit": "a" * 40,
            "pull_request_base_commit": "b" * 40,
        },
        recorded_at_utc=recorded_at_utc,
    )


def _write_manifest(path: Path, entry: dict[str, object]) -> None:
    path.write_text(
        json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def test_registry_digest_is_independent_of_incremental_import_order(tmp_path: Path) -> None:
    earlier = _entry("2026-07-21T15:01:16.374294+00:00")
    later = _entry("2026-07-21T16:01:16.374294+00:00")
    earlier_manifest = tmp_path / "earlier.jsonl"
    later_manifest = tmp_path / "later.jsonl"
    forward_registry = tmp_path / "forward.jsonl"
    reverse_registry = tmp_path / "reverse.jsonl"
    _write_manifest(earlier_manifest, earlier)
    _write_manifest(later_manifest, later)

    merge_experiment_manifests(forward_registry, [earlier_manifest])
    forward = merge_experiment_manifests(forward_registry, [later_manifest])
    merge_experiment_manifests(reverse_registry, [later_manifest])
    reverse = merge_experiment_manifests(reverse_registry, [earlier_manifest])

    assert forward_registry.read_bytes() == reverse_registry.read_bytes()
    assert forward.registry_sha256 == reverse.registry_sha256
    assert [entry["run_id"] for entry in load_manifest_entries(forward_registry)] == [
        earlier["run_id"],
        later["run_id"],
    ]
