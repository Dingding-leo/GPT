from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

_REPOSITORY_ROOT = Path(__file__).parents[1]
_ANALYSIS_PATH = (
    _REPOSITORY_ROOT
    / "reports"
    / "research"
    / "lagged-cross-market-correlation-regimes"
    / "analysis.py"
)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")
_FIXTURE_DIR = (
    Path(__file__).parent / "fixtures" / "okx" / "btc_eth_asset_strategy_oos_20200111_20200514"
)
_SPEC = importlib.util.spec_from_file_location("lagged_cross_market_correlation", _ANALYSIS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {_ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis)


def _load_fixture() -> tuple[pd.DataFrame, dict[str, object]]:
    csv_path = _FIXTURE_DIR / "returns.csv"
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == metadata["fixture_sha256"]
    assert metadata["provider"] == "OKX"
    assert metadata["market_type"] == "spot"
    assert metadata["timeframe"] == "1Dutc"
    assert metadata["instruments"] == ["BTC-USDT", "ETH-USDT"]
    frame = pd.read_csv(csv_path)
    index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
    frame.index = index
    assert len(frame) == metadata["observations"] == 125
    assert index[0].isoformat() == metadata["start"]
    assert index[-1].isoformat() == metadata["end"]
    assert bool(((index[1:] - index[:-1]) == pd.Timedelta(days=1)).all())
    return frame, metadata


def test_regime_uses_only_prior_asset_returns() -> None:
    frame, _ = _load_fixture()
    original = analysis.lagged_correlation_regimes(frame)
    eligible_timestamp = original["regime"].dropna().index[0]
    altered = frame.copy()
    altered.loc[eligible_timestamp, "BTC-USDT_asset_return"] += 0.25
    altered.loc[eligible_timestamp, "ETH-USDT_asset_return"] -= 0.25
    changed = analysis.lagged_correlation_regimes(altered)

    assert (
        changed.loc[eligible_timestamp, "lagged_correlation"]
        == original.loc[eligible_timestamp, "lagged_correlation"]
    )
    assert (
        changed.loc[eligible_timestamp, "prior_expanding_median"]
        == original.loc[eligible_timestamp, "prior_expanding_median"]
    )
    assert changed.loc[eligible_timestamp, "regime"] == original.loc[eligible_timestamp, "regime"]


def test_regime_means_match_independent_real_fixture_calculation() -> None:
    frame, _ = _load_fixture()
    calculated = analysis.lagged_correlation_regimes(frame)
    lagged_btc = frame["BTC-USDT_asset_return"].shift(1)
    lagged_eth = frame["ETH-USDT_asset_return"].shift(1)
    correlation = lagged_btc.rolling(60, min_periods=60).corr(lagged_eth)
    threshold = correlation.expanding(min_periods=60).median().shift(1)
    independent_labels = pd.Series(pd.NA, index=frame.index, dtype="string")
    eligible = correlation.notna() & threshold.notna()
    independent_labels.loc[eligible & correlation.ge(threshold)] = "above_prior_median"
    independent_labels.loc[eligible & correlation.lt(threshold)] = "below_prior_median"

    pd.testing.assert_series_equal(
        calculated["regime"], independent_labels.rename("regime"), check_names=True
    )
    observed = analysis.conditional_annualized_means(frame, calculated["regime"])
    for market in analysis.MARKETS:
        for regime in analysis.REGIMES:
            expected = float(
                frame.loc[independent_labels.eq(regime), f"{market}_strategy_return"].mean() * 365
            )
            assert observed[market][regime] == expected


def test_moving_blocks_are_paired_contiguous_and_deterministic() -> None:
    first = analysis.moving_block_indices(120, block_length=20, rng=np.random.default_rng(20260722))
    second = analysis.moving_block_indices(
        120, block_length=20, rng=np.random.default_rng(20260722)
    )
    assert np.array_equal(first, second)
    assert len(first) == 120
    assert first.min() >= 0
    assert first.max() < 120
    for start in range(0, 120, 20):
        block = first[start : start + 20]
        assert np.array_equal(np.diff(block), np.ones(19, dtype=int))


def test_committed_result_records_single_rejected_candidate_and_provenance() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"]["candidates_searched"] == 1
    assert result["candidate_accounting"]["candidates_passed"] == 0
    assert result["candidate_accounting"]["candidates_rejected"] == 1
    assert result["verdict"] == "rejected"
    assert result["data_summary"]["observations_per_market"] == 2340
    assert result["data_summary"]["warmup_observations"] == 120
    assert result["data_summary"]["eligible_observations"] == 2220
    assert sum(result["data_summary"]["regime_observations"].values()) == 2220
    assert result["provenance"]["source_workflow_run_id"] == 29898899644
    assert result["provenance"]["source_artifact_id"] == 8521103926
    assert result["provenance"]["source_checkout_sha"] == (
        "cadd23dde47d235d549056b5459c51ea4cdf8e9f"
    )
    assert result["provenance"]["return_file_sha256"] == analysis.RETURN_FILE_SHA256
    lower_bounds = [
        result["results"][market][regime]["confidence_interval"]["lower"]
        for market in analysis.MARKETS
        for regime in analysis.REGIMES
    ]
    assert all(lower <= 0.0 for lower in lower_bounds)
