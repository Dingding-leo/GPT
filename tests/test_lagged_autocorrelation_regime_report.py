from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT
    / "reports"
    / "research"
    / "lagged-autocorrelation-regimes"
    / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = (
    Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
)
SPEC = importlib.util.spec_from_file_location("lagged_autocorrelation_regimes", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _real_asset_returns() -> pd.DataFrame:
    rows = json.loads((FIXTURE_DIR / "rows.json").read_text(encoding="utf-8"))
    metadata = json.loads((FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert len(rows) == metadata["observations"] == 5

    chronological = list(reversed(rows))
    timestamps = pd.DatetimeIndex(
        [datetime.fromtimestamp(int(row[0]) / 1_000, UTC) for row in chronological]
    )
    closes = pd.Series([float(row[4]) for row in chronological], index=timestamps)
    asset_returns = closes.pct_change().iloc[1:]
    return asset_returns.to_frame("asset_return")


def test_lagged_autocorrelation_matches_independent_prior_only_calculation() -> None:
    frame = _real_asset_returns()
    classified = analysis.classify_autocorrelation_regimes(
        frame, lookback=3, require_both_regimes=False
    )
    assert len(classified) == 1

    prior_values = frame["asset_return"].iloc[:3].to_numpy(dtype=float)
    expected = float(np.corrcoef(prior_values[:-1], prior_values[1:])[0, 1])
    actual = float(classified.iloc[0]["lagged_autocorrelation"])
    assert actual == expected
    assert classified.iloc[0]["regime"] == ("positive" if expected > 0.0 else "nonpositive")


def test_current_return_cannot_change_its_own_regime_label() -> None:
    frame = _real_asset_returns()
    baseline = analysis.classify_autocorrelation_regimes(
        frame, lookback=3, require_both_regimes=False
    )
    altered = frame.copy()
    altered.iloc[-1, altered.columns.get_loc("asset_return")] *= -3.0
    modified = analysis.classify_autocorrelation_regimes(
        altered, lookback=3, require_both_regimes=False
    )

    pd.testing.assert_series_equal(
        baseline["lagged_autocorrelation"],
        modified["lagged_autocorrelation"],
        check_exact=True,
    )
    pd.testing.assert_series_equal(baseline["regime"], modified["regime"], check_exact=True)


def test_moving_blocks_are_deterministic_and_contiguous_inside_each_block() -> None:
    first = analysis.moving_block_indices(
        180,
        block_length=20,
        resamples=4,
        seed=20260722,
    )
    second = analysis.moving_block_indices(
        180,
        block_length=20,
        resamples=4,
        seed=20260722,
    )
    np.testing.assert_array_equal(first, second)
    assert first.shape == (4, 180)
    for sample in first:
        for start in range(0, len(sample), 20):
            np.testing.assert_array_equal(np.diff(sample[start : start + 20]), np.ones(19))


def test_committed_result_records_one_rejected_candidate_and_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    assert result["canonical_signature"] == analysis.SIGNATURE
    assert result["candidate_count"] == 1
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["verdict"] == "reject"
    assert result["verdict"] == "rejected"
    assert result["source"]["provider"] == "OKX"
    assert result["source"]["artifact_id"] == 8523312240
    assert result["source"]["artifact_sha256"] == analysis.SOURCE_ARTIFACT_SHA256
    assert result["source"]["development_markets"] is True
    assert result["markets"]["BTC-USDT"]["observations"] == 2280
    assert result["markets"]["ETH-USDT"]["observations"] == 2280
    assert result["markets"]["ETH-USDT"]["regimes"]["nonpositive"]["passes"] is True
    assert result["markets"]["ETH-USDT"]["regimes"]["positive"]["passes"] is False
