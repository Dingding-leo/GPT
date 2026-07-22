from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

_ANALYSIS_PATH = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "lagged-liquidity-regimes"
    / "analysis.py"
)
_SPEC = importlib.util.spec_from_file_location("lagged_liquidity_regime_analysis", _ANALYSIS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"unable to load {_ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis)

_VOLUME_FIXTURE_DIR = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc-usdt-1dutc-volume-20191201-20200219"
)
_RETURNS_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc_eth_oos_20200111_20200219"
    / "btc_usdt_returns.csv"
)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_fixture_inputs() -> tuple[pd.Series, pd.DataFrame]:
    metadata = json.loads((_VOLUME_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    volume_path = _VOLUME_FIXTURE_DIR / "volume_quote.csv"
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert metadata["field"] == "volume_quote"
    assert metadata["fixture_csv_sha256"] == _sha256(volume_path)
    assert metadata["source_artifact_id"] == 8523312240
    assert metadata["source_member_sha256"] == (
        "b0bd7c6c7e30fcc095073169f60bde24559f481b24cc6f4bdfb85349f57974bb"
    )
    assert _sha256(_RETURNS_PATH) == (
        "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587"
    )

    volume_frame = pd.read_csv(volume_path)
    volume_index = analysis.explicit_daily_utc_index(volume_frame["timestamp"], label="volume")
    volume = pd.Series(
        pd.to_numeric(volume_frame["volume_quote"], errors="raise").to_numpy(dtype=float),
        index=volume_index,
        name="volume_quote",
    )
    returns = pd.read_csv(_RETURNS_PATH)
    return_index = analysis.explicit_daily_utc_index(returns["timestamp"], label="return")
    return_frame = pd.DataFrame(
        {
            "fold": np.ones(len(returns), dtype=int),
            "strategy_return": pd.to_numeric(
                returns["strategy_return"], errors="raise"
            ).to_numpy(dtype=float),
        },
        index=return_index,
    )
    return volume, return_frame


def test_real_volume_fixture_drives_prior_only_fold_threshold() -> None:
    volume, returns = _load_fixture_inputs()
    classified, thresholds = analysis.classify_liquidity_regimes(
        volume,
        returns,
        liquidity_lookback=10,
        selection_bars=30,
    )

    assert len(classified) == 40
    assert set(classified["regime"]) == {"high", "low"}
    assert thresholds == [
        {
            "fold": 1,
            "test_start": "2020-01-11T00:00:00+00:00",
            "selection_observations": 30,
            "valid_liquidity_observations": 30,
            "threshold_volume_quote": thresholds[0]["threshold_volume_quote"],
        }
    ]
    expected_threshold = float(
        volume.shift(1).rolling(10, min_periods=10).median().loc[: "2020-01-10"].tail(30).median()
    )
    assert thresholds[0]["threshold_volume_quote"] == expected_threshold


def test_future_volume_changes_cannot_change_earlier_regime_labels() -> None:
    volume, returns = _load_fixture_inputs()
    baseline, _ = analysis.classify_liquidity_regimes(
        volume,
        returns,
        liquidity_lookback=10,
        selection_bars=30,
    )
    altered = volume.copy()
    altered.loc[altered.index > pd.Timestamp("2020-02-15T00:00:00Z")] *= 1000.0
    changed, _ = analysis.classify_liquidity_regimes(
        altered,
        returns,
        liquidity_lookback=10,
        selection_bars=30,
    )

    unchanged = baseline.index <= pd.Timestamp("2020-02-15T00:00:00Z")
    pd.testing.assert_series_equal(
        baseline.loc[unchanged, "regime"],
        changed.loc[unchanged, "regime"],
    )
    pd.testing.assert_series_equal(
        baseline.loc[unchanged, "lagged_liquidity"],
        changed.loc[unchanged, "lagged_liquidity"],
    )


def test_moving_block_indices_are_seeded_and_contiguous_inside_blocks() -> None:
    first = analysis.moving_block_indices(40, block_length=5, resamples=8, seed=20260722)
    second = analysis.moving_block_indices(40, block_length=5, resamples=8, seed=20260722)
    different = analysis.moving_block_indices(40, block_length=5, resamples=8, seed=20260723)

    np.testing.assert_array_equal(first, second)
    assert not np.array_equal(first, different)
    assert first.shape == (8, 40)
    for sample in first:
        for block in sample.reshape(-1, 5):
            np.testing.assert_array_equal(np.diff(block), np.ones(4, dtype=int))


def test_committed_result_records_complete_rejection_and_provenance() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.SIGNATURE
    assert result["candidate_count"] == 1
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["verdict"] == "reject"
    assert result["verdict"] == "rejected"
    assert result["source"]["workflow_run_id"] == 29904635219
    assert result["source"]["artifact_id"] == 8523312240
    assert result["source"]["artifact_sha256"] == (
        "5e8578dcc2aed7edbbc30b02b25cdb62ef7c01614305afeb09a940184c8d70a4"
    )
    assert set(result["markets"]) == {"BTC-USDT", "ETH-USDT"}
    assert all(market["observations"] == 2340 for market in result["markets"].values())
    assert result["markets"]["BTC-USDT"]["regimes"]["low"]["passes"] is False
    assert result["markets"]["ETH-USDT"]["regimes"]["high"]["passes"] is False
    assert result["markets"]["ETH-USDT"]["regimes"]["low"]["passes"] is False
    assert len(result["failure_reasons"]) == 3
