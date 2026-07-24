from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import pytest

from gpt_quant.experiment_registry import (
    _registry_lock,
    load_manifest_entries,
    merge_experiment_manifests,
)
from gpt_quant.reproducibility import build_experiment_manifest_entry, file_sha256

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _entry(recorded_at_utc: str) -> dict[str, object]:
    return build_experiment_manifest_entry(
        effective_config={"data": {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"}},
        data_hashes={
            "normalized_csv": file_sha256(_CANDLES),
            "raw_pages": file_sha256(_RAW),
        },
        data_paths={"normalized_csv": _CANDLES, "raw_pages": _RAW},
        artifact_paths={"fixture_metadata": _METADATA},
        candidate_count=27,
        result_classification="fixture-only registry lock test; no performance claim",
        instrument_id="BTC-USDT",
        bar="1Dutc",
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


def _merge_in_spawned_process(
    registry: str,
    manifest: str,
    started: multiprocessing.synchronize.Event,
    completed: multiprocessing.synchronize.Event,
    result_queue: multiprocessing.queues.Queue,
) -> None:
    started.set()
    try:
        result = merge_experiment_manifests(registry, [manifest])
        result_queue.put(("ok", result.total_runs))
    except BaseException as exc:  # pragma: no cover - surfaced in the parent assertion
        result_queue.put(("error", repr(exc)))
    finally:
        completed.set()


@pytest.mark.skipif(os.name not in {"posix", "nt"}, reason="platform has no registry lock backend")
def test_registry_updates_wait_for_cross_process_lock(tmp_path: Path) -> None:
    first = _entry("2026-07-21T15:01:16.374294+00:00")
    second = _entry("2026-07-21T16:01:16.374294+00:00")
    first_manifest = tmp_path / "first.jsonl"
    second_manifest = tmp_path / "second.jsonl"
    registry = tmp_path / "registry.jsonl"
    _write_manifest(first_manifest, first)
    _write_manifest(second_manifest, second)
    merge_experiment_manifests(registry, [first_manifest])

    context = multiprocessing.get_context("spawn")
    started = context.Event()
    completed = context.Event()
    result_queue = context.Queue()
    process = context.Process(
        target=_merge_in_spawned_process,
        args=(str(registry), str(second_manifest), started, completed, result_queue),
    )

    try:
        with _registry_lock(registry):
            process.start()
            assert started.wait(timeout=10.0)
            assert completed.wait(timeout=0.5) is False
            assert process.is_alive()

        assert completed.wait(timeout=10.0)
        process.join(timeout=10.0)
        assert process.exitcode == 0
        assert result_queue.get(timeout=5.0) == ("ok", 2)
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5.0)
        result_queue.close()

    stored = load_manifest_entries(registry)
    assert {entry["run_id"] for entry in stored} == {first["run_id"], second["run_id"]}
