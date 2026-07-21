from __future__ import annotations

import json
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
