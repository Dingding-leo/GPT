from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT
    / "reports"
    / "research"
    / "conditional-drawdown-vs-volatility-benchmark"
    / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
METADATA_PATH = FIXTURE_DIR / "metadata.json"
FIXTURE_PATHS = {
    "BTC-USDT": FIXTURE_DIR / "btc_usdt_returns.csv",
    "ETH-USDT": FIXTURE_DIR / "eth_usdt_returns.csv",
}


def _load_analysis():
    spec = importlib.util.spec_from_file_location("conditional_drawdown_analysis", ANALYSIS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_returns(market: str) -> np.ndarray:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["market_type"] == "spot"
    assert metadata["timeframe"] == "1Dutc"
    instrument = metadata["instruments"][market]
    fixture_path = FIXTURE_PATHS[market]
    assert hashlib.sha256(fixture_path.read_bytes()).hexdigest() == instrument["fixture_sha256"]
    frame = pd.read_csv(fixture_path)
    return frame["strategy_return"].to_numpy(dtype=float)


def _conditional_drawdown(values: np.ndarray, tail_fraction: float) -> float:
    nav = np.concatenate(([1.0], np.cumprod(1.0 + values)))
    drawdowns = (nav / np.maximum.accumulate(nav) - 1.0)[1:]
    tail_count = math.ceil(len(drawdowns) * tail_fraction)
    return float(np.mean(np.sort(drawdowns)[:tail_count]))


def test_conditional_drawdown_uses_initial_nav_and_deepest_real_drawdowns() -> None:
    analysis = _load_analysis()
    returns = _fixture_returns("BTC-USDT")

    observed = analysis.conditional_drawdown_at_risk(returns, 0.10)

    assert observed == pytest.approx(_conditional_drawdown(returns, 0.10))


def test_bootstrap_resamples_paired_real_return_rows_and_recomputes_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    strategy = _fixture_returns("BTC-USDT")
    benchmark = _fixture_returns("ETH-USDT")
    sample_indices = (
        np.concatenate((np.arange(0, 20), np.arange(10, 30))),
        np.concatenate((np.arange(20, 40), np.arange(5, 25))),
    )
    samples = iter(sample_indices)
    monkeypatch.setattr(
        analysis,
        "moving_block_indices",
        lambda observation_count, block_length, rng: next(samples),
    )

    result = analysis.bootstrap_conditional_drawdown_delta(
        strategy,
        benchmark,
        tail_fraction=0.10,
        block_length=20,
        resamples=2,
        confidence=0.95,
        seed=19,
    )

    expected_deltas = [
        _conditional_drawdown(strategy[indices], 0.10)
        - _conditional_drawdown(benchmark[indices], 0.10)
        for indices in sample_indices
    ]
    assert result["ci_lower"] == pytest.approx(np.quantile(expected_deltas, 0.025))
    assert result["ci_upper"] == pytest.approx(np.quantile(expected_deltas, 0.975))
    assert result["probability_delta_positive"] == pytest.approx(
        np.mean(np.asarray(expected_deltas) > 0.0)
    )


def test_moving_blocks_are_deterministic_and_contiguous() -> None:
    analysis = _load_analysis()
    first = analysis.moving_block_indices(40, 10, np.random.default_rng(20260723))
    second = analysis.moving_block_indices(40, 10, np.random.default_rng(20260723))

    np.testing.assert_array_equal(first, second)
    assert len(first) == 40
    assert int(first.min()) >= 0
    assert int(first.max()) < 40
    for start in range(0, 40, 10):
        np.testing.assert_array_equal(np.diff(first[start : start + 10]), np.ones(9))


def test_result_records_single_rejected_candidate_and_bound_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["provenance"]["source_artifact_id"] == 8552853195
    assert result["provenance"]["source_artifact_sha256"] == (
        "462f6ea87ea0501916645e936282eeaecef9ed004723e6ec61a1ad63ced6c9e5"
    )
    assert result["markets"]["BTC-USDT"]["observations"] == 2385
    assert result["markets"]["ETH-USDT"]["observations"] == 2385
    assert result["markets"]["BTC-USDT"]["ci_lower"] > 0.0
    assert result["markets"]["ETH-USDT"]["ci_lower"] <= 0.0
    assert result["markets"]["BTC-USDT"]["observed_delta"] == pytest.approx(0.4288754936776258)
    assert result["markets"]["ETH-USDT"]["observed_delta"] == pytest.approx(0.3502239741818459)
