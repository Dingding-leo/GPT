from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import gpt_quant.okx_1h as okx_1h_module
from gpt_quant.okx import OKXCandleSnapshot
from gpt_quant.okx_1h import (
    _is_exact_hour_index,
    fetch_okx_one_hour_candles,
    replay_persisted_okx_one_hour_snapshot,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT"


def _real_snapshot() -> OKXCandleSnapshot:
    source = json.loads((_FIXTURE_DIR / "SOURCE.json").read_text(encoding="utf-8"))
    for evidence in source["fixture_files"].values():
        path = Path(evidence["path"])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]
    return replay_persisted_okx_one_hour_snapshot(_FIXTURE_DIR, inst_id="BTC-USDT")


def test_exact_hour_check_uses_vectorized_datetime_index_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    index = _real_snapshot().candles.index

    def fail_iteration(self: pd.DatetimeIndex):
        pytest.fail("exact-hour validation regressed to Python timestamp iteration")

    monkeypatch.setattr(pd.DatetimeIndex, "__iter__", fail_iteration)

    assert _is_exact_hour_index(index)


def test_one_hour_fetch_rejects_structurally_misaligned_real_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _real_snapshot()
    candles = real.candles.copy()
    timestamp_ns = candles.index.asi8.copy()
    timestamp_ns[1] += 1_000_000_000
    candles.index = pd.DatetimeIndex(timestamp_ns, tz="UTC", name=candles.index.name)
    corrupted = OKXCandleSnapshot(
        candles=candles,
        raw_pages=real.raw_pages,
        metadata=dict(real.metadata),
    )
    monkeypatch.setattr(
        okx_1h_module,
        "fetch_okx_history_candles",
        lambda **kwargs: corrupted,
    )

    with pytest.raises(ValueError, match="not aligned to an exact UTC hour"):
        fetch_okx_one_hour_candles(
            inst_id="BTC-USDT",
            start=real.candles.index[0],
            end=real.candles.index[-1],
            pause_seconds=0.0,
            get_json=lambda url, timeout: pytest.fail("unexpected page request"),
        )
