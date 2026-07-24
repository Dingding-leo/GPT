from __future__ import annotations

import json
from pathlib import Path

import pytest

from gpt_quant.experiment_registry import merge_experiment_manifests
from gpt_quant.reproducibility import build_experiment_manifest_entry, file_sha256

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _real_okx_manifest_entry() -> dict[str, object]:
    return build_experiment_manifest_entry(
        effective_config={
            "data": {
                "provider": "OKX",
                "instrument_id": "BTC-USDT",
                "bar": "1Dutc",
            }
        },
        data_hashes={
            "normalized_csv": file_sha256(_CANDLES),
            "raw_pages": file_sha256(_RAW),
        },
        data_paths={"normalized_csv": _CANDLES, "raw_pages": _RAW},
        artifact_paths={"fixture_metadata": _METADATA},
        candidate_count=27,
        result_classification="fixture-only canonical-source test; no performance claim",
        instrument_id="BTC-USDT",
        bar="1Dutc",
        code_provenance={
            "checkout_commit": "c" * 40,
            "pull_request_head_commit": "a" * 40,
            "pull_request_base_commit": "b" * 40,
        },
        recorded_at_utc="2026-07-21T15:01:16.374294+00:00",
    )


def test_registry_rejects_noncanonical_source_without_creating_output(tmp_path: Path) -> None:
    entry = _real_okx_manifest_entry()
    manifest = tmp_path / "manifest.jsonl"
    registry = tmp_path / "registry.jsonl"
    manifest.write_text(
        json.dumps(entry, ensure_ascii=False, separators=(", ", ": ")) + "\n",
        encoding="utf-8",
    )
    original_manifest = manifest.read_bytes()

    with pytest.raises(ValueError, match="not canonical JSONL"):
        merge_experiment_manifests(registry, [manifest])

    assert manifest.read_bytes() == original_manifest
    assert not registry.exists()
