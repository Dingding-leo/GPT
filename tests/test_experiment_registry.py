from __future__ import annotations

import json
from pathlib import Path

import pytest

from gpt_quant.experiment_registry import (
    load_manifest_entries,
    merge_experiment_manifests,
)
from gpt_quant.reproducibility import (
    build_experiment_manifest_entry,
    canonical_json_sha256,
    file_sha256,
)

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _entry_v1(recorded_at_utc: str) -> dict[str, object]:
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
        "result_classification": "fixture-only registry test; no performance claim",
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


def _entry_v2(recorded_at_utc: str) -> dict[str, object]:
    return build_experiment_manifest_entry(
        effective_config={"data": {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"}},
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
        code_provenance={
            "checkout_commit": "c" * 40,
            "pull_request_head_commit": "a" * 40,
            "pull_request_base_commit": "b" * 40,
        },
        recorded_at_utc=recorded_at_utc,
    )


def _write_manifest(path: Path, entries: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for entry in entries
        ),
        encoding="utf-8",
    )


def test_registry_tracks_exact_reruns_and_is_idempotent(tmp_path: Path) -> None:
    first = _entry_v2("2026-07-21T15:01:16.374294+00:00")
    rerun = _entry_v2("2026-07-21T16:01:16.374294+00:00")
    manifest = tmp_path / "manifest.jsonl"
    registry = tmp_path / "registry.jsonl"
    _write_manifest(manifest, [rerun, first])

    initial = merge_experiment_manifests(registry, [manifest])
    repeated = merge_experiment_manifests(registry, [manifest])
    stored = load_manifest_entries(registry)

    assert initial.appended_runs == 2
    assert initial.total_runs == 2
    assert repeated.appended_runs == 0
    assert repeated.skipped_runs == 2
    assert [entry["recorded_at_utc"] for entry in stored] == sorted(
        [first["recorded_at_utc"], rerun["recorded_at_utc"]]
    )
    assert len({entry["experiment_id"] for entry in stored}) == 1
    assert len({entry["run_id"] for entry in stored}) == 2


def test_registry_preserves_schema_one_compatibility(tmp_path: Path) -> None:
    legacy = _entry_v1("2026-07-21T15:01:16.374294+00:00")
    current = _entry_v2("2026-07-21T16:01:16.374294+00:00")
    manifest = tmp_path / "manifest.jsonl"
    registry = tmp_path / "registry.jsonl"
    _write_manifest(manifest, [current, legacy])

    result = merge_experiment_manifests(registry, [manifest])
    stored = load_manifest_entries(registry)

    assert result.appended_runs == 2
    assert [entry["schema_version"] for entry in stored] == [1, 2]
    assert "code_provenance" not in stored[0]
    assert stored[1]["code_provenance"] == current["code_provenance"]


def test_registry_output_is_independent_of_manifest_argument_order(
    tmp_path: Path,
) -> None:
    first = _entry_v2("2026-07-21T15:01:16.374294+00:00")
    rerun = _entry_v2("2026-07-21T16:01:16.374294+00:00")
    earlier = tmp_path / "a-manifest.jsonl"
    later = tmp_path / "b-manifest.jsonl"
    left = tmp_path / "left.jsonl"
    right = tmp_path / "right.jsonl"
    _write_manifest(earlier, [rerun])
    _write_manifest(later, [first])

    left_result = merge_experiment_manifests(left, [earlier, later])
    right_result = merge_experiment_manifests(right, [later, earlier])

    assert left.read_bytes() == right.read_bytes()
    assert left_result.registry_sha256 == right_result.registry_sha256


def test_registry_rejects_experiment_id_collision(tmp_path: Path) -> None:
    valid = _entry_v2("2026-07-21T15:01:16.374294+00:00")
    collision = dict(valid)
    collision["code_commit"] = "d" * 40
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, [collision])

    with pytest.raises(ValueError, match="checkout_commit must match code_commit"):
        merge_experiment_manifests(tmp_path / "registry.jsonl", [manifest])


def test_registry_rejects_unpaired_pull_request_revision(tmp_path: Path) -> None:
    valid = _entry_v2("2026-07-21T15:01:16.374294+00:00")
    invalid = dict(valid)
    invalid["code_provenance"] = {
        "checkout_commit": "c" * 40,
        "pull_request_head_commit": "a" * 40,
    }
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, [invalid])

    with pytest.raises(ValueError, match="must be provided together"):
        merge_experiment_manifests(tmp_path / "registry.jsonl", [manifest])


def test_registry_rejects_unbound_extra_fields(tmp_path: Path) -> None:
    invalid = _entry_v1("2026-07-21T15:01:16.374294+00:00")
    invalid["pull_request_head_commit"] = "a" * 40
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, [invalid])

    with pytest.raises(ValueError, match="unsupported keys"):
        merge_experiment_manifests(tmp_path / "registry.jsonl", [manifest])


def test_registry_rejects_run_id_collision(tmp_path: Path) -> None:
    valid = _entry_v2("2026-07-21T15:01:16.374294+00:00")
    collision = dict(valid)
    collision["artifact_sha256"] = {"fixture_metadata": "f" * 64}
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, [collision])

    with pytest.raises(ValueError, match="run_id does not match"):
        merge_experiment_manifests(tmp_path / "registry.jsonl", [manifest])


def test_registry_rejects_malformed_existing_json(tmp_path: Path) -> None:
    registry = tmp_path / "registry.jsonl"
    registry.write_text("{not json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="invalid JSON on line 1"):
        merge_experiment_manifests(registry, [])


def test_registry_rejects_noncanonical_existing_jsonl(tmp_path: Path) -> None:
    registry = tmp_path / "registry.jsonl"
    entry = _entry_v2("2026-07-21T15:01:16.374294+00:00")
    registry.write_text(
        json.dumps(entry, ensure_ascii=False, separators=(", ", ": ")) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="not canonical JSONL"):
        merge_experiment_manifests(registry, [])


def test_registry_rejects_non_utc_recorded_at_timestamp(tmp_path: Path) -> None:
    entry = _entry_v1("2026-07-22T00:31:16.374294+09:30")
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, [entry])

    with pytest.raises(ValueError, match="recorded_at_utc must be expressed in UTC"):
        merge_experiment_manifests(tmp_path / "registry.jsonl", [manifest])


def test_registry_rejects_noncanonical_utc_timestamp(tmp_path: Path) -> None:
    entry = _entry_v1("2026-07-21T15:01:16.374294Z")
    manifest = tmp_path / "manifest.jsonl"
    _write_manifest(manifest, [entry])

    with pytest.raises(ValueError, match="canonical UTC ISO-8601 form"):
        merge_experiment_manifests(tmp_path / "registry.jsonl", [manifest])
