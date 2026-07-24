from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

_MODULE_PATH = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "portfolio-drawdown-diversification"
    / "analysis.py"
)
_SPEC = importlib.util.spec_from_file_location("portfolio_drawdown_analysis", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"unable to load {_MODULE_PATH}")
analysis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis)

_FIXTURE = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_RESULT = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "portfolio-drawdown-diversification"
    / "result.json"
)


def _real_sleeve_returns() -> np.ndarray:
    btc = pd.read_csv(_FIXTURE / "btc_usdt_returns.csv")
    eth = pd.read_csv(_FIXTURE / "eth_usdt_returns.csv")
    assert btc["timestamp"].equals(eth["timestamp"])
    return np.column_stack(
        [
            btc["strategy_return"].to_numpy(dtype=float),
            eth["strategy_return"].to_numpy(dtype=float),
        ]
    )


def test_no_rebalance_portfolio_matches_independent_nav_calculation() -> None:
    returns = _real_sleeve_returns()
    actual = analysis.no_rebalance_portfolio_returns(returns)
    sleeve_nav = np.cumprod(1.0 + returns, axis=0)
    portfolio_nav = 0.5 * sleeve_nav[:, 0] + 0.5 * sleeve_nav[:, 1]
    expected = np.empty(len(portfolio_nav))
    expected[0] = portfolio_nav[0] - 1.0
    expected[1:] = portfolio_nav[1:] / portfolio_nav[:-1] - 1.0
    np.testing.assert_allclose(actual, expected, rtol=0.0, atol=1e-15)


def test_paired_block_indices_preserve_observed_cross_market_rows() -> None:
    returns = _real_sleeve_returns()
    indices = analysis.moving_block_indices(
        len(returns),
        analysis.BLOCK_LENGTH,
        np.random.default_rng(analysis.SEED),
    )
    sampled = returns[indices]
    for row, source_index in zip(sampled, indices, strict=True):
        np.testing.assert_array_equal(row, returns[source_index])


def test_committed_result_records_single_rejected_candidate() -> None:
    result = json.loads(_RESULT.read_text(encoding="utf-8"))
    assert result["candidate_count"] == 1
    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert all(
        comparison["bootstrap"]["ci_lower"] <= 0.0
        for comparison in result["portfolio"]["comparisons"].values()
    )
