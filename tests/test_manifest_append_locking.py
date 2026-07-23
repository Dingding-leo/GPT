from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

import pytest

from gpt_quant import append_experiment_manifest
from gpt_quant.experiment_registry import _registry_lock, load_manifest_entries
from gpt_quant.reproducibility import build_experiment_manifest_entry

_FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc"
_CANDLES = _FIXTURE_ROOT / "candles.csv"
_RAW = _FIXTURE_ROOT / "raw.json"
_METADATA = _FIXTURE_ROOT / "metadata.json"


def _entry() -> dict[str, object]:
    metadata = json.loads(_METADATA.read_text(encoding="utf-8"))
    return build_experiment_manifest_entry(
        effective_config={
            "data": {"provider": "OKX", "instrument_id": "BTC-USDT", "bar": "1Dutc"},
            "search": {"candidate_count": 27},
        },
        data_hashes={
            "normalized_csv": str(metadata["fixture_normalized_csv_sha256"]),
            "raw_pages": str(metadata["fixture_raw_json_sha256"]),
        },
        data_paths={"normalized_csv": _CANDLES, "raw_pages": _RAW},
        artifact_paths={"fixture_metadata": _METADATA},
        candidate_count=27,
        result_classification="fixture-only manifest lock test; no performance claim",
        instrument_id="BTC-USDT",
        bar="1Dutc",
        code_commit="c" * 40,
        recorded_at_utc="2026-07-21T15:01:16.374294+00:00",
    )


def _append_in_spawned_process(
    manifest: str,
    entry: dict[str, object],
    started: multiprocessing.synchronize.Event,
    completed: multiprocessing.synchronize.Event,
    result_queue: multiprocessing.queues.Queue,
) -> None:
    started.set()
    try:
        _, appended = append_experiment_manifest(manifest, entry)
        result_queue.put(("ok", appended))
    except BaseException as exc:  # pragma: no cover - surfaced in the parent assertion
        result_queue.put(("error", repr(exc)))
    finally:
        completed.set()


@pytest.mark.skipif(os.name not in {"posix", "nt"}, reason="platform has no manifest lock backend")
def test_manifest_append_waits_for_cross_process_lock(tmp_path: Path) -> None:
    entry = _entry()
    manifest = tmp_path / "experiment-manifest.jsonl"

    context = multiprocessing.get_context("spawn")
    started = context.Event()
    completed = context.Event()
    result_queue = context.Queue()
    process = context.Process(
        target=_append_in_spawned_process,
        args=(str(manifest), entry, started, completed, result_queue),
    )

    try:
        with _registry_lock(manifest):
            process.start()
            assert started.wait(timeout=10.0)
            assert completed.wait(timeout=0.5) is False
            assert process.is_alive()

        assert completed.wait(timeout=10.0)
        process.join(timeout=10.0)
        assert process.exitcode == 0
        assert result_queue.get(timeout=5.0) == ("ok", True)
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=5.0)
        result_queue.close()

    stored = load_manifest_entries(manifest, require_canonical=True)
    assert [stored_entry["run_id"] for stored_entry in stored] == [entry["run_id"]]
