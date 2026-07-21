from __future__ import annotations

import hashlib
import json
import shutil
import struct
import zlib
from pathlib import Path

import conftest as fixture_loader
import pandas as pd
import pytest


def test_okx_fixture_is_complete_daily_history(btc_usdt_prices: pd.Series) -> None:
    assert len(btc_usdt_prices) == 900
    assert btc_usdt_prices.index[0] == pd.Timestamp("2018-01-11T00:00:00+00:00")
    assert btc_usdt_prices.index[-1] == pd.Timestamp("2020-06-28T00:00:00+00:00")
    assert btc_usdt_prices.index.is_monotonic_increasing
    assert not btc_usdt_prices.index.has_duplicates
    assert btc_usdt_prices.index.to_series().diff().dropna().eq(pd.Timedelta(days=1)).all()
    assert (btc_usdt_prices > 0.0).all()


def test_okx_fixture_rejects_tampered_close_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tampered_path = tmp_path / "closes.json"
    closes = json.loads(fixture_loader._CLOSES_PATH.read_text(encoding="utf-8"))
    closes[0] = float(closes[0]) + 1.0
    tampered_path.write_text(json.dumps(closes), encoding="utf-8")
    monkeypatch.setattr(fixture_loader, "_CLOSES_PATH", tampered_path)

    with pytest.raises(RuntimeError, match="fixture hash does not match"):
        fixture_loader._load_btc_usdt_prices()


def test_okx_fixture_rejects_hashed_duplicate_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    closes_path = tmp_path / "closes.json"
    timestamps_path = tmp_path / "timestamps.zlib"
    metadata_path = tmp_path / "metadata.json"
    shutil.copyfile(fixture_loader._CLOSES_PATH, closes_path)

    payload = zlib.decompress(fixture_loader._TIMESTAMPS_PATH.read_bytes())
    timestamps = [value[0] for value in struct.iter_unpack(">q", payload)]
    timestamps[3] = timestamps[2]
    altered = zlib.compress(
        b"".join(struct.pack(">q", value) for value in timestamps),
        level=9,
    )
    timestamps_path.write_bytes(altered)

    metadata = json.loads(fixture_loader._METADATA_PATH.read_text(encoding="utf-8"))
    metadata["fixture_timestamps_sha256"] = hashlib.sha256(altered).hexdigest()
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    monkeypatch.setattr(fixture_loader, "_FIXTURE_DIR", tmp_path)
    monkeypatch.setattr(fixture_loader, "_CLOSES_PATH", closes_path)
    monkeypatch.setattr(fixture_loader, "_TIMESTAMPS_PATH", timestamps_path)
    monkeypatch.setattr(fixture_loader, "_METADATA_PATH", metadata_path)

    with pytest.raises(RuntimeError, match="timestamps must be unique"):
        fixture_loader._load_btc_usdt_prices()
