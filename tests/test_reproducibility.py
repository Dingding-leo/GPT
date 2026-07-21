from __future__ import annotations

import json

import pytest

from gpt_quant.reproducibility import (
    append_experiment_manifest,
    build_experiment_manifest_entry,
    canonical_json_sha256,
    file_sha256,
)


def test_canonical_json_hash_is_independent_of_mapping_order() -> None:
    left = {"b": [2, 1], "a": {"y": 2, "x": 1}}
    right = {"a": {"x": 1, "y": 2}, "b": [2, 1]}

    assert canonical_json_sha256(left) == canonical_json_sha256(right)


def test_manifest_entry_records_config_data_and_artifact_hashes(tmp_path) -> None:
    report = tmp_path / "walk_forward.json"
    returns = tmp_path / "walk_forward_returns.csv"
    candles = tmp_path / "candles.csv"
    raw = tmp_path / "raw.json"
    report.write_text('{"sharpe":1.25}\n', encoding="utf-8")
    returns.write_text("timestamp,strategy_return\n2026-01-01,0.01\n", encoding="utf-8")
    candles.write_text("timestamp,close\n2026-01-01,1\n", encoding="utf-8")
    raw.write_text("[]\n", encoding="utf-8")
    timestamp = "2026-07-21T14:00:00+00:00"

    entry = build_experiment_manifest_entry(
        effective_config={
            "strategy": {"lookback": 30},
            "search": {"weights": [0.5, 0.7]},
        },
        data_hashes={
            "normalized_csv": file_sha256(candles),
            "raw_pages": file_sha256(raw),
        },
        data_paths={"normalized_csv": candles, "raw_pages": raw},
        artifact_paths={"report": report, "returns": returns},
        candidate_count=27,
        result_classification="reject: test fixture",
        instrument_id="BTC-USDT",
        bar="1Dutc",
        code_commit="c" * 40,
        recorded_at_utc=timestamp,
    )

    assert entry["code_commit"] == "c" * 40
    assert entry["config_sha256"] == canonical_json_sha256(
        {"strategy": {"lookback": 30}, "search": {"weights": [0.5, 0.7]}}
    )
    assert entry["data_sha256"] == {
        "normalized_csv": file_sha256(candles),
        "raw_pages": file_sha256(raw),
    }
    assert entry["artifact_sha256"] == {
        "report": file_sha256(report),
        "returns": file_sha256(returns),
    }
    assert entry["candidate_count"] == 27
    assert entry["experiment_id"].startswith("exp-")
    assert entry["run_id"].startswith("run-")


def test_manifest_entry_rejects_data_hash_mismatch(tmp_path) -> None:
    candles = tmp_path / "candles.csv"
    artifact = tmp_path / "artifact.txt"
    candles.write_text("timestamp,close\n2026-01-01,1\n", encoding="utf-8")
    artifact.write_text("stable\n", encoding="utf-8")

    with pytest.raises(ValueError, match="data hash mismatch for 'normalized_csv'"):
        build_experiment_manifest_entry(
            effective_config={"a": 1},
            data_hashes={"normalized_csv": "0" * 64},
            data_paths={"normalized_csv": candles},
            artifact_paths={"artifact": artifact},
            candidate_count=1,
            result_classification="reject",
            instrument_id="ETH-USDT",
            bar="1Dutc",
            code_commit="e" * 40,
            recorded_at_utc="2026-07-21T14:01:00+00:00",
        )


def test_manifest_entry_rejects_incomplete_data_path_mapping(tmp_path) -> None:
    candles = tmp_path / "candles.csv"
    raw = tmp_path / "raw.json"
    artifact = tmp_path / "artifact.txt"
    candles.write_text("timestamp,close\n2026-01-01,1\n", encoding="utf-8")
    raw.write_text("[]\n", encoding="utf-8")
    artifact.write_text("stable\n", encoding="utf-8")

    with pytest.raises(ValueError, match="data_paths keys must exactly match"):
        build_experiment_manifest_entry(
            effective_config={"a": 1},
            data_hashes={
                "normalized_csv": file_sha256(candles),
                "raw_pages": file_sha256(raw),
            },
            data_paths={"normalized_csv": candles},
            artifact_paths={"artifact": artifact},
            candidate_count=1,
            result_classification="reject",
            instrument_id="ETH-USDT",
            bar="1Dutc",
            code_commit="e" * 40,
            recorded_at_utc="2026-07-21T14:01:00+00:00",
        )


def test_manifest_append_is_canonical_and_idempotent(tmp_path) -> None:
    artifact = tmp_path / "artifact.txt"
    artifact.write_text("stable\n", encoding="utf-8")
    entry = build_experiment_manifest_entry(
        effective_config={"a": 1},
        data_hashes={"normalized_csv": "d" * 64},
        artifact_paths={"artifact": artifact},
        candidate_count=1,
        result_classification="reject",
        instrument_id="ETH-USDT",
        bar="1Dutc",
        code_commit="e" * 40,
        recorded_at_utc="2026-07-21T14:01:00+00:00",
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
    assert lines[0] == json.dumps(
        entry, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
