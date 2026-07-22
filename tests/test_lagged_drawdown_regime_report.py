from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "lagged-drawdown-regimes" / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc-usdt-1dutc-raw-20260717-20260721"
SPEC = importlib.util.spec_from_file_location("lagged_drawdown_regimes", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _real_close_frame() -> pd.DataFrame:
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
    frame = closes.to_frame("close")
    frame["lagged_drawdown"] = analysis.lagged_drawdown(frame["close"], lookback=3)
    return frame


def test_lagged_drawdown_matches_independent_prior_only_calculation() -> None:
    frame = _real_close_frame()
    prior_closes = frame["close"].iloc[1:4]
    expected = float(prior_closes.iloc[-1] / prior_closes.max() - 1.0)
    actual = float(frame["lagged_drawdown"].iloc[-1])

    assert actual == expected
    assert actual == 0.0


def test_real_fixture_classifies_underwater_then_prior_high_without_current_data() -> None:
    snapshot = _real_close_frame()
    test_index = snapshot.index[-2:]
    real_returns = snapshot["close"].pct_change().reindex(test_index)
    returns = pd.DataFrame(
        {"strategy_return": real_returns.to_numpy(dtype=float), "fold": [1, 1]},
        index=test_index,
    )
    fold_reports = [
        {
            "fold": 1,
            "test_start": test_index[0].isoformat(),
            "test_end": test_index[-1].isoformat(),
        }
    ]

    classified = analysis.classify_drawdown_regimes(
        snapshot,
        returns,
        fold_reports,
        test_bars=2,
    )

    assert classified["regime"].tolist() == ["underwater", "at_high"]
    assert classified["lagged_drawdown"].iloc[0] < 0.0
    assert classified["lagged_drawdown"].iloc[1] == 0.0


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
    assert result["source"]["artifact_id"] == analysis.SOURCE_ARTIFACT_ID
    assert result["source"]["artifact_sha256"] == analysis.SOURCE_ARTIFACT_SHA256
    assert result["source"]["development_markets"] is True
    assert result["markets"]["BTC-USDT"]["observations"] == 2340
    assert result["markets"]["ETH-USDT"]["observations"] == 2340
    assert result["markets"]["BTC-USDT"]["regimes"]["at_high"]["passes"] is False
    assert result["markets"]["BTC-USDT"]["regimes"]["underwater"]["passes"] is False
    assert result["markets"]["ETH-USDT"]["regimes"]["at_high"]["passes"] is False
    assert result["markets"]["ETH-USDT"]["regimes"]["underwater"]["passes"] is False
