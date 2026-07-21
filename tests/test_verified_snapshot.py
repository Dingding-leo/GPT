from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from gpt_quant import load_verified_price_snapshot

_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc-usdt-1dutc-600"
)


def test_verified_snapshot_loads_expected_real_market_window() -> None:
    snapshot = load_verified_price_snapshot(_FIXTURE_DIR / "manifest.json")

    assert snapshot.metadata["provider"] == "OKX"
    assert snapshot.metadata["instrument_id"] == "BTC-USDT"
    assert snapshot.metadata["bar"] == "1Dutc"
    assert len(snapshot.prices) == 600
    assert snapshot.prices.index[0] == pd.Timestamp("2024-11-28T00:00:00Z")
    assert snapshot.prices.index[-1] == pd.Timestamp("2026-07-20T00:00:00Z")


def test_verified_snapshot_rejects_modified_market_bytes(tmp_path: Path) -> None:
    copied = tmp_path / "snapshot"
    shutil.copytree(_FIXTURE_DIR, copied)
    with (copied / "part-001.csv").open("a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(ValueError, match="snapshot SHA-256 mismatch"):
        load_verified_price_snapshot(copied / "manifest.json")
