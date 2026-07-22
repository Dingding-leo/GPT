from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).parents[1]
ANALYSIS_PATH = ROOT / "reports/research/weekday-weekend-consistency/analysis.py"
RESULT_PATH = ROOT / "reports/research/weekday-weekend-consistency/result.json"
FIXTURE = ROOT / "tests/fixtures/okx/btc_eth_oos_20200111_20200219/btc_usdt_returns.csv"
FIXTURE_SHA256 = "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("weekday_weekend_analysis", ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conditional_means_match_independent_real_fixture_calculation() -> None:
    analysis = _load_analysis()
    frame = analysis.load_returns(FIXTURE, expected_sha256=FIXTURE_SHA256)
    labels = analysis.regime_labels(frame["timestamp"])
    actual = analysis.conditional_annualized_means(frame["strategy_return"].to_numpy(), labels)

    independent = frame.assign(
        regime=np.where(frame["timestamp"].dt.weekday >= 5, "weekend", "weekday")
    )
    expected = independent.groupby("regime")["strategy_return"].mean() * 365

    assert actual["weekday"] == pytest.approx(expected["weekday"], abs=1e-15)
    assert actual["weekend"] == pytest.approx(expected["weekend"], abs=1e-15)


def test_moving_blocks_are_deterministic_and_keep_observed_pairs() -> None:
    analysis = _load_analysis()
    frame = analysis.load_returns(FIXTURE, expected_sha256=FIXTURE_SHA256)
    first = analysis.moving_block_indices(40, block_length=7, resamples=5, seed=17)
    second = analysis.moving_block_indices(40, block_length=7, resamples=5, seed=17)

    np.testing.assert_array_equal(first, second)
    original = dict(zip(frame["timestamp"], frame["strategy_return"], strict=True))
    sampled = frame.iloc[first[0]]
    for timestamp, value in zip(sampled["timestamp"], sampled["strategy_return"], strict=True):
        assert value == original[timestamp]


def test_committed_result_records_complete_single_candidate_rejection() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert len(result["candidates"]) == 1
    assert result["verdict"] == "reject"
    assert result["canonical_signature"].endswith("candidate_count=1")
    assert set(result["markets"]) == {"BTC-USDT", "ETH-USDT"}
    assert all(market["observations"] == 2340 for market in result["markets"].values())
    assert result["markets"]["ETH-USDT"]["regimes"]["weekend"]["passes"] is True
    assert len(result["failure_reasons"]) == 3
