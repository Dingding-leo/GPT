from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "lagged-skewness-regimes" / "analysis.py"
)
RESULT_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "lagged-skewness-regimes" / "result.json"
)
FIXTURE_DIR = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "okx"
    / "btc-usdt-1dutc-raw-20260717-20260721"
)

SPEC = importlib.util.spec_from_file_location("lagged_skewness_regime_analysis", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _real_close_series() -> pd.Series:
    rows_path = FIXTURE_DIR / "rows.json"
    metadata = json.loads((FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    rows_bytes = rows_path.read_bytes()
    rows = json.loads(rows_bytes)

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert hashlib.sha256(rows_bytes).hexdigest() == metadata["fixture_rows_sha256"]
    assert len(rows) == metadata["observations"] == 5

    chronological = list(reversed(rows))
    index = pd.DatetimeIndex(
        pd.to_datetime([int(row[0]) for row in chronological], unit="ms", utc=True)
    )
    return pd.Series([float(row[4]) for row in chronological], index=index, name="close")


def test_lagged_skewness_uses_only_prior_real_returns() -> None:
    close = _real_close_series()
    skewness = analysis.lagged_return_skewness(close, lookback=3)
    prior_returns = close.pct_change(fill_method=None).iloc[1:4]

    assert skewness.iloc[-1] == pytest.approx(prior_returns.skew(), abs=1e-15)

    current_close_changed = close.copy()
    current_close_changed.iloc[-1] *= 1.01
    changed = analysis.lagged_return_skewness(current_close_changed, lookback=3)
    assert changed.iloc[-1] == pytest.approx(skewness.iloc[-1], abs=1e-15)


def test_moving_blocks_are_deterministic_and_contiguous() -> None:
    first = analysis.moving_block_indices(5, block_length=2, resamples=4, seed=20260722)
    second = analysis.moving_block_indices(5, block_length=2, resamples=4, seed=20260722)

    np.testing.assert_array_equal(first, second)
    assert first.shape == (4, 5)
    for sample in first:
        assert sample[1] == sample[0] + 1
        assert sample[3] == sample[2] + 1


def test_committed_result_records_complete_rejection() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "rejected"
    assert result["provenance"]["source_artifact_sha256"] == analysis.SOURCE_ARTIFACT_SHA256
    assert result["method"]["current_session_excluded"] is True

    for market in analysis.MARKETS:
        regimes = result["markets"][market]["regimes"]
        assert set(regimes) == {"positive", "nonpositive"}
        assert sum(regime["observations"] for regime in regimes.values()) == 2340
        assert all(regime["passes"] is False for regime in regimes.values())
        assert all(regime["confidence_interval"]["lower"] <= 0.0 for regime in regimes.values())
