from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

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


def _snapshot():
    rows = _real_rows()

    def getter(url: str, timeout: float) -> dict[str, object]:
        return {"code": "0", "msg": "", "data": rows}

    return fetch_okx_history_candles(
        inst_id="BTC-USDT",
        bar="1Dutc",
        limit=len(rows),
        max_pages=1,
        pause_seconds=0.0,
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
