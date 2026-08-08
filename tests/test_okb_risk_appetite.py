from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.run_okb_risk_appetite import (
    FEE_ONE_WAY,
    ROUND_TRIP_FEE,
    TRAIN_END,
    TRAIN_START,
    _finite_positive_ohlc,
    _standardized_slope,
    _tercile_effect,
    _training_anchors,
)

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx_1h" / "BTC-USDT"
_FIXTURE_CSV = _FIXTURE_DIR / "okx-BTC-USDT-1H.csv"


def _real_btc_fixture() -> pd.DataFrame:
    source = json.loads((_FIXTURE_DIR / "SOURCE.json").read_text(encoding="utf-8"))
    expected_sha = source["fixture_files"]["candles"]["sha256"]
    assert hashlib.sha256(_FIXTURE_CSV.read_bytes()).hexdigest() == expected_sha
    frame = pd.read_csv(_FIXTURE_CSV, parse_dates=["timestamp"])
    return frame.set_index("timestamp")


def test_training_anchor_maturity_guard_never_reads_sealed_oos() -> None:
    anchors = _training_anchors()
    assert anchors[0] == TRAIN_START
    assert anchors[-1] == 10_752
    pairs = zip(anchors[:-1], anchors[1:], strict=True)
    assert all(right - left == 24 for left, right in pairs)
    assert all(anchor + 25 < TRAIN_END for anchor in anchors)
    assert 10_776 not in anchors


def test_standardized_slope_is_per_one_feature_standard_deviation() -> None:
    closes = _real_btc_fixture()["close"].to_numpy(dtype=float)
    slope = _standardized_slope(closes, closes)
    assert slope == pytest.approx(float(np.std(closes, ddof=0)))


def test_tercile_effect_and_ohlc_use_immutable_real_fixture() -> None:
    candles = _real_btc_fixture()
    closes = candles["close"].to_numpy(dtype=float)
    opens = candles["open"].to_numpy(dtype=float)
    order = np.argsort(closes, kind="mergesort")
    expected = float(opens[order[-1]] - opens[order[0]])
    assert _tercile_effect(closes, opens) == pytest.approx(expected)
    assert _finite_positive_ohlc(candles)


def test_fee_contract_is_exactly_five_bps_one_way() -> None:
    assert FEE_ONE_WAY == pytest.approx(0.0005)
    assert ROUND_TRIP_FEE == pytest.approx(0.0010)
