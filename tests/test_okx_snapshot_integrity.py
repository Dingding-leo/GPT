from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import gpt_quant.okx as okx_module
from gpt_quant.okx import fetch_okx_history_candles, write_okx_snapshot

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"


def _real_rows() -> list[list[str]]:
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    rows_bytes = _ROWS_PATH.read_bytes()
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert hashlib.sha256(rows_bytes).hexdigest() == metadata["fixture_rows_sha256"]
    rows = json.loads(rows_bytes)
    return [list(row) for row in rows]


def _snapshot(*, end: str | None = None):
    rows = _real_rows()

    def getter(url: str, timeout: float) -> dict[str, object]:
        return {"code": "0", "msg": "", "data": rows}

    return fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        limit=len(rows),
        max_pages=1,
        pause_seconds=0.0,
        end=end,
        get_json=getter,
    )


def test_writer_rejects_mutated_candles_before_creating_files(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.candles.iloc[-1, snapshot.candles.columns.get_loc("close")] += 1.0
    output = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="candles changed after download"):
        write_okx_snapshot(snapshot, output)

    assert not output.exists()


def test_writer_rejects_mutated_raw_pages_even_with_replaced_metadata_hash(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.raw_pages[0]["data"][1][4] = "65260.4"
    canonical_raw = (
        json.dumps(
            snapshot.raw_pages,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    snapshot.metadata["raw_pages_sha256"] = hashlib.sha256(canonical_raw).hexdigest()
    output = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="raw pages changed after download"):
        write_okx_snapshot(snapshot, output)

    assert not output.exists()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [("instrument_id", "ETH-USDT"), ("bar", "1H")],
)
def test_writer_rejects_relabelled_metadata_before_creating_files(
    tmp_path: Path,
    field: str,
    replacement: str,
) -> None:
    snapshot = _snapshot()
    snapshot.metadata[field] = replacement
    output = tmp_path / "snapshot"

    with pytest.raises(ValueError, match="metadata changed after download"):
        write_okx_snapshot(snapshot, output)

    assert not output.exists()


def test_writer_persists_unchanged_source_bound_snapshot(tmp_path: Path) -> None:
    snapshot = _snapshot()
    paths = write_okx_snapshot(snapshot, tmp_path / "snapshot")

    assert (
        hashlib.sha256(paths["candles"].read_bytes()).hexdigest()
        == snapshot.metadata["normalized_csv_sha256"]
    )
    assert (
        hashlib.sha256(paths["raw"].read_bytes()).hexdigest()
        == snapshot.metadata["raw_pages_sha256"]
    )


@pytest.mark.parametrize("output_preexisted", [False, True])
def test_writer_rolls_back_partial_snapshot_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output_preexisted: bool,
) -> None:
    output = tmp_path / "snapshot"
    previous_payloads: dict[str, bytes] = {}
    if output_preexisted:
        previous_paths = write_okx_snapshot(_snapshot(end="2026-07-19"), output)
        previous_payloads = {name: path.read_bytes() for name, path in previous_paths.items()}
        (output / "caller-owned.txt").write_text("preserve me", encoding="utf-8")

    real_replace = okx_module.os.replace
    replace_calls = 0

    def fail_metadata_commit(source: str | Path, destination: str | Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 3:
            raise OSError("injected metadata commit failure")
        real_replace(source, destination)

    monkeypatch.setattr(okx_module.os, "replace", fail_metadata_commit)

    with pytest.raises(OSError, match="injected metadata commit failure"):
        write_okx_snapshot(_snapshot(), output)

    if output_preexisted:
        assert (output / "caller-owned.txt").read_text(encoding="utf-8") == "preserve me"
        current_paths = {
            "candles": output / "okx-BTC-USDT-1Dutc.csv",
            "raw": output / "okx-BTC-USDT-1Dutc.raw.json",
            "metadata": output / "okx-BTC-USDT-1Dutc.metadata.json",
        }
        assert {
            name: path.read_bytes() for name, path in current_paths.items()
        } == previous_payloads
        assert sorted(path.name for path in output.iterdir()) == [
            "caller-owned.txt",
            "okx-BTC-USDT-1Dutc.csv",
            "okx-BTC-USDT-1Dutc.metadata.json",
            "okx-BTC-USDT-1Dutc.raw.json",
        ]
    else:
        assert not output.exists()


def test_writer_reports_incomplete_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "snapshot"
    write_okx_snapshot(_snapshot(end="2026-07-19"), output)
    (output / "caller-owned.txt").write_text("preserve me", encoding="utf-8")

    real_replace = okx_module.os.replace
    replace_calls = 0

    def fail_commit_and_first_restore(source: str | Path, destination: str | Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 3:
            raise OSError("injected metadata commit failure")
        if replace_calls == 4:
            raise OSError("injected raw rollback failure")
        real_replace(source, destination)

    monkeypatch.setattr(okx_module.os, "replace", fail_commit_and_first_restore)

    with pytest.raises(
        RuntimeError,
        match=(
            "OKX snapshot commit failed and rollback was incomplete: "
            "raw: injected raw rollback failure"
        ),
    ) as exc_info:
        write_okx_snapshot(_snapshot(), output)

    assert isinstance(exc_info.value.__cause__, OSError)
    assert str(exc_info.value.__cause__) == "injected metadata commit failure"
    assert (output / "caller-owned.txt").read_text(encoding="utf-8") == "preserve me"
    assert not any(path.name.startswith(".okx-snapshot-") for path in output.iterdir())
