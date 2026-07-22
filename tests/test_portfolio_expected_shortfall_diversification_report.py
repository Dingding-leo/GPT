from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

_MODULE_PATH = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "portfolio-expected-shortfall-diversification"
    / "analysis.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "portfolio_expected_shortfall_analysis", _MODULE_PATH
)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"unable to load {_MODULE_PATH}")
analysis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis)

_FIXTURE = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_RESULT = (
    Path(__file__).parents[1]
    / "reports"
    / "research"
    / "portfolio-expected-shortfall-diversification"
    / "result.json"
)
_EXPECTED_FIXTURE_HASHES = {
    "btc_usdt_returns.csv": "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587",
    "eth_usdt_returns.csv": "552401a2e90368ac675915b067a575287d993b46bd355ff17e8a68ff847d8db8",
}


def _real_sleeve_returns() -> np.ndarray:
    for filename, expected_sha256 in _EXPECTED_FIXTURE_HASHES.items():
        actual_sha256 = hashlib.sha256((_FIXTURE / filename).read_bytes()).hexdigest()
        assert actual_sha256 == expected_sha256
    btc = pd.read_csv(_FIXTURE / "btc_usdt_returns.csv")
    eth = pd.read_csv(_FIXTURE / "eth_usdt_returns.csv")
    assert btc["timestamp"].equals(eth["timestamp"])
    return np.column_stack(
        [
            btc["strategy_return"].to_numpy(dtype=float),
            eth["strategy_return"].to_numpy(dtype=float),
        ]
    )


def test_real_fixture_portfolio_and_expected_shortfall_match_independent_calculation() -> None:
    returns = _real_sleeve_returns()
    actual_portfolio = analysis.no_rebalance_portfolio_returns(returns)

    sleeve_nav = np.cumprod(1.0 + returns, axis=0)
    portfolio_nav = 0.5 * sleeve_nav[:, 0] + 0.5 * sleeve_nav[:, 1]
    expected_portfolio = np.empty(len(portfolio_nav))
    expected_portfolio[0] = portfolio_nav[0] - 1.0
    expected_portfolio[1:] = portfolio_nav[1:] / portfolio_nav[:-1] - 1.0
    np.testing.assert_allclose(actual_portfolio, expected_portfolio, rtol=0.0, atol=1e-15)

    tail_count = math.ceil(len(actual_portfolio) * analysis.TAIL_FRACTION)
    independent_expected_shortfall = float(np.sort(actual_portfolio)[:tail_count].mean())
    assert analysis.expected_shortfall(actual_portfolio) == independent_expected_shortfall


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


def test_committed_result_records_one_rejected_candidate_and_all_failures() -> None:
    result = json.loads(_RESULT.read_text(encoding="utf-8"))
    assert result["candidate_count"] == 1
    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["verdict"] == "rejected"
    assert result["joint_supported"] is False
    assert result["failure_reasons"] == [
        "portfolio expected-shortfall reduction versus BTC-USDT lower confidence bound "
        "is not positive"
    ]
    comparisons = result["portfolio"]["comparisons"]
    assert comparisons["BTC-USDT"]["bootstrap"]["ci_lower"] <= 0.0
    assert comparisons["ETH-USDT"]["bootstrap"]["ci_lower"] > 0.0
    assert result["provenance"]["source_artifact_sha256"] == (
        "b1f271e4267cc1c1007bbccd11c53c1a59d3f1e3fe3f1e3f07423c6907b83605"
    )
