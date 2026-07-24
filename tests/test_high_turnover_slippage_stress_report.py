from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).parents[1]
ANALYSIS_PATH = ROOT / "reports/research/high-turnover-slippage-stress/analysis.py"
RESULT_PATH = ROOT / "reports/research/high-turnover-slippage-stress/result.json"
FIXTURE = ROOT / "tests/fixtures/okx/btc_eth_oos_20200111_20200219/btc_usdt_returns.csv"
FIXTURE_SHA256 = "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587"
# Exact first-40 turnover extract from workflow 29894309496 attempt 2,
# artifact 8519440629, BTC return-file SHA-256 539a8a77...676cf73.
REAL_BTC_TURNOVER_FIRST_40 = np.array(
    [
        0.0,
        0.0,
        0.0,
        0.0,
        0.0067468133660427,
        0.0067468133660427,
        0.0630160482750374,
        0.0792834893452638,
        0.0999440710520749,
        0.0423554665682263,
        0.1029364301311189,
        0.1640947221865024,
        0.0466281598158144,
        0.3136593121334357,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.1797026081369255,
        0.0818757061738731,
        0.0852421800617419,
        0.1722840222891941,
        0.0960918055523943,
        0.065275634342692,
        0.0461812742411656,
        0.0077131089805814,
        0.0184949317108836,
        0.0469798208249097,
        0.1268240541797019,
        0.0035192046152967,
        0.0495034874307711,
    ],
    dtype=float,
)


def _load_analysis():
    spec = importlib.util.spec_from_file_location("high_turnover_slippage_analysis", ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_returns() -> np.ndarray:
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == FIXTURE_SHA256
    frame = pd.read_csv(FIXTURE)
    return pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(dtype=float)


def test_concentrated_slippage_matches_independent_real_fixture_calculation() -> None:
    analysis = _load_analysis()
    returns = _fixture_returns()

    actual, stressed_count = analysis.apply_concentrated_slippage(
        REAL_BTC_TURNOVER_FIRST_40,
        returns,
        high_turnover_fraction=0.10,
        extra_slippage_bps=20.0,
    )

    independent = pd.DataFrame(
        {
            "turnover": REAL_BTC_TURNOVER_FIRST_40,
            "strategy_return": returns,
        }
    )
    stressed_rows = independent.nlargest(4, "turnover", keep="first").index
    expected = independent["strategy_return"].copy()
    expected.loc[stressed_rows] -= independent.loc[stressed_rows, "turnover"] * 20.0 / 10_000.0

    assert stressed_count == 4
    np.testing.assert_allclose(actual, expected.to_numpy(), rtol=0.0, atol=0.0)


def test_moving_blocks_are_deterministic_and_preserve_observed_pairs() -> None:
    analysis = _load_analysis()
    returns = _fixture_returns()
    first = analysis.moving_block_indices(40, block_length=7, resamples=5, seed=17)
    second = analysis.moving_block_indices(40, block_length=7, resamples=5, seed=17)

    np.testing.assert_array_equal(first, second)
    observed_pairs = set(zip(REAL_BTC_TURNOVER_FIRST_40, returns, strict=True))
    sampled_pairs = zip(
        REAL_BTC_TURNOVER_FIRST_40[first[0]],
        returns[first[0]],
        strict=True,
    )
    assert all(pair in observed_pairs for pair in sampled_pairs)


def test_committed_result_records_complete_single_candidate_rejection() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert len(result["candidates"]) == 1
    assert result["verdict"] == "reject"
    assert result["canonical_signature"].endswith("candidate_count=1")
    assert result["provenance"]["source_artifact_id"] == 8519440629
    assert set(result["markets"]) == {"BTC-USDT", "ETH-USDT"}
    assert all(market["observations"] == 2340 for market in result["markets"].values())
    assert all(market["stressed_observations"] == 234 for market in result["markets"].values())
    assert all(market["passes"] is False for market in result["markets"].values())
    assert len(result["failure_reasons"]) == 2
    assert result["markets"]["BTC-USDT"]["stressed_annualized_arithmetic_mean"] == pytest.approx(
        0.15491011936671342
    )
