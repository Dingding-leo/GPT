from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from gpt_quant import OKXCandleSnapshot, parse_okx_candle_rows

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "run_okx_research.py"
_SCRIPT_SPEC = importlib.util.spec_from_file_location("run_okx_research", _SCRIPT_PATH)
if _SCRIPT_SPEC is None or _SCRIPT_SPEC.loader is None:
    raise RuntimeError(f"unable to load OKX research CLI from {_SCRIPT_PATH}")
run_okx_research = importlib.util.module_from_spec(_SCRIPT_SPEC)
_SCRIPT_SPEC.loader.exec_module(run_okx_research)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
_ROWS_PATH = _FIXTURE_DIR / "rows.json"
_METADATA_PATH = _FIXTURE_DIR / "metadata.json"
_EXPECTED_FIXTURE_SHA256 = "dcb30e58e10f8415aefe8c206f99c21fc8862b3b4f5ea65679a01262980c5481"


def _real_okx_rows() -> list[list[str]]:
    rows_bytes = _ROWS_PATH.read_bytes()
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["fixture_rows_sha256"] == _EXPECTED_FIXTURE_SHA256
    assert hashlib.sha256(rows_bytes).hexdigest() == _EXPECTED_FIXTURE_SHA256
    return json.loads(rows_bytes)


def _timestamp_iso(row: list[str]) -> str:
    return datetime.fromtimestamp(int(row[0]) / 1_000, UTC).isoformat()


def _snapshot(rows: list[list[str]]) -> OKXCandleSnapshot:
    candles = parse_okx_candle_rows(rows)
    candles = candles.loc[candles["confirm"] == "1"].copy()
    raw_pages = ({"code": "0", "msg": "", "data": rows},)
    metadata = {
        "provider": "OKX",
        "instrument_id": "BTC-USDT",
        "bar": "1Dutc",
        "expected_step_seconds": 86_400,
    }
    return OKXCandleSnapshot(candles=candles, raw_pages=raw_pages, metadata=metadata)


def test_explicit_end_accepts_latest_completed_candle_at_boundary() -> None:
    _partial, day_20, day_19, _day_18, _day_17 = _real_okx_rows()
    snapshot = _snapshot([day_20, day_19])

    run_okx_research._validate_requested_end_coverage(
        snapshot,
        requested_end=_timestamp_iso(day_20),
    )


def test_explicit_end_rejects_history_missing_boundary_candle() -> None:
    _partial, day_20, day_19, day_18, _day_17 = _real_okx_rows()
    snapshot = _snapshot([day_19, day_18])

    with pytest.raises(ValueError, match="does not cover the requested end"):
        run_okx_research._validate_requested_end_coverage(
            snapshot,
            requested_end=_timestamp_iso(day_20),
        )


def test_cli_rejects_missing_end_coverage_before_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _partial, day_20, day_19, day_18, _day_17 = _real_okx_rows()
    snapshot = _snapshot([day_19, day_18])
    output_dir = tmp_path / "reports"

    monkeypatch.setattr(
        run_okx_research,
        "parse_args",
        lambda: argparse.Namespace(
            config="unused.json",
            inst_id="BTC-USDT",
            bar="1Dutc",
            base_url="https://example.test",
            start=None,
            end=_timestamp_iso(day_20),
            max_pages=1,
            output_dir=str(output_dir),
            manifest_path=None,
        ),
    )
    monkeypatch.setattr(
        run_okx_research,
        "load_json",
        lambda path: {
            "data": {"limit": 2, "pause_seconds": 0.0, "timeout": 20.0},
            "strategy": {},
            "search": {},
            "robustness": {},
        },
    )
    monkeypatch.setattr(
        run_okx_research,
        "fetch_okx_history_candles",
        lambda **kwargs: snapshot,
    )

    def unexpected_write(*args: object, **kwargs: object) -> None:
        pytest.fail("snapshot persistence ran before requested-end coverage validation")

    monkeypatch.setattr(run_okx_research, "write_okx_snapshot", unexpected_write)

    with pytest.raises(ValueError, match="does not cover the requested end"):
        run_okx_research.main()

    assert not output_dir.exists()
