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


def _entry(timestamp: str) -> dict[str, object]:
    return build_experiment_manifest_entry(
        effective_config={
            "data": {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"},
            "fee": {"one_way_bps": 5.0},
            "friction": {
                "spread": "not_modeled",
                "slippage": "not_modeled",
                "market_impact": "not_modeled",
                "latency": "not_modeled",
            },
        },
        data_hashes={
            "normalized_csv": file_sha256(_CANDLES),
            "raw_pages": file_sha256(_RAW),
        },
        data_paths={"normalized_csv": _CANDLES, "raw_pages": _RAW},
        artifact_paths={"fixture_metadata": _METADATA},
        candidate_count=27,
        result_classification="fixture-only registry test; no performance claim",
        instrument_id="BTC-USDT",
        bar="1Dutc",
        code_commit="c" * 40,
        recorded_at_utc=timestamp,
    )


def _write_manifest(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for entry in entries
        ),
        encoding="utf-8",
    )


def test_registry_preserves_reruns_and_exact_remerge_is_idempotent(tmp_path: Path) -> None:
    first = _entry("2026-07-21T15:01:16.374294+00:00")
    second = _entry("2026-07-22T15:01:16.374294+00:00")
    assert first["experiment_id"] == second["experiment_id"]
    assert first["run_id"] != second["run_id"]

    manifest = tmp_path / "manifest.jsonl"
    registry = tmp_path / "registry.jsonl"
    _write_manifest(manifest, [first, second])

    result = merge_experiment_manifests(registry, [manifest])
    original_bytes = registry.read_bytes()
    repeated = merge_experiment_manifests(registry, [manifest])

    assert result.added_runs == 2
    assert result.skipped_runs == 0
    assert repeated.added_runs == 0
    assert repeated.skipped_runs == 2
    assert registry.read_bytes() == original_bytes
    assert result.registry_sha256 == repeated.registry_sha256 == file_sha256(registry)
    assert [json.loads(line) for line in registry.read_text().splitlines()] == [first, second]


def test_registry_rejects_identity_tampering_without_replacing_prior_state(
    tmp_path: Path,
) -> None:
    first = _entry("2026-07-21T15:01:16.374294+00:00")
    valid = tmp_path / "valid.jsonl"
    registry = tmp_path / "registry.jsonl"
    _write_manifest(valid, [first])
    merge_experiment_manifests(registry, [valid])
    prior_bytes = registry.read_bytes()

    tampered = dict(first)
    tampered["experiment_id"] = "exp-" + "0" * 24
    invalid = tmp_path / "invalid.jsonl"
    _write_manifest(invalid, [tampered])

    with pytest.raises(ValueError, match="experiment_id does not match"):
        merge_experiment_manifests(registry, [invalid])
    assert registry.read_bytes() == prior_bytes


def test_registry_rejects_duplicate_existing_run_ids(tmp_path: Path) -> None:
    entry = _entry("2026-07-21T15:01:16.374294+00:00")
    registry = tmp_path / "registry.jsonl"
    incoming = tmp_path / "incoming.jsonl"
    _write_manifest(registry, [entry, entry])
    _write_manifest(incoming, [entry])

    with pytest.raises(ValueError, match="registry contains duplicate run_id"):
        merge_experiment_manifests(registry, [incoming])


def test_registry_rejects_noncanonical_or_malformed_jsonl(tmp_path: Path) -> None:
    entry = _entry("2026-07-21T15:01:16.374294+00:00")
    registry = tmp_path / "registry.jsonl"
    noncanonical = tmp_path / "noncanonical.jsonl"
    noncanonical.write_text(json.dumps(entry, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="is not canonical JSONL"):
        merge_experiment_manifests(registry, [noncanonical])

    malformed = tmp_path / "malformed.jsonl"
    malformed.write_text('{"run_id":\n', encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        merge_experiment_manifests(registry, [malformed])
