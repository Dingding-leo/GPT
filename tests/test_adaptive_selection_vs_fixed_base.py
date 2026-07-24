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
    REPOSITORY_ROOT / "reports" / "research" / "adaptive-selection-vs-fixed-base" / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = REPOSITORY_ROOT / "tests" / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
SPEC = importlib.util.spec_from_file_location("adaptive_selection_vs_fixed_base", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _real_fixture_returns() -> tuple[np.ndarray, np.ndarray]:
    btc_path = FIXTURE_DIR / "btc_usdt_returns.csv"
    eth_path = FIXTURE_DIR / "eth_usdt_returns.csv"
    assert hashlib.sha256(btc_path.read_bytes()).hexdigest() == (
        "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587"
    )
    assert hashlib.sha256(eth_path.read_bytes()).hexdigest() == (
        "552401a2e90368ac675915b067a575287d993b46bd355ff17e8a68ff847d8db8"
    )
    btc = pd.to_numeric(pd.read_csv(btc_path)["strategy_return"], errors="raise").to_numpy(
        dtype=float
    )
    eth = pd.to_numeric(pd.read_csv(eth_path)["strategy_return"], errors="raise").to_numpy(
        dtype=float
    )
    return btc, eth


def test_moving_blocks_are_seeded_non_circular_and_contiguous() -> None:
    first = analysis.moving_block_indices(
        40,
        block_length=8,
        rng=np.random.default_rng(20260722),
    )
    second = analysis.moving_block_indices(
        40,
        block_length=8,
        rng=np.random.default_rng(20260722),
    )

    np.testing.assert_array_equal(first, second)
    assert len(first) == 40
    assert int(first.min()) >= 0
    assert int(first.max()) < 40
    for start in range(0, 40, 8):
        np.testing.assert_array_equal(np.diff(first[start : start + 8]), np.ones(7, dtype=int))


def test_paired_bootstrap_uses_one_shared_index_path_per_resample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    btc, eth = _real_fixture_returns()
    calls = 0

    def fixed_indices(
        observations: int,
        *,
        block_length: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        nonlocal calls
        calls += 1
        assert observations == 40
        assert block_length == 8
        assert isinstance(rng, np.random.Generator)
        return np.arange(observations, dtype=int)

    monkeypatch.setattr(analysis, "moving_block_indices", fixed_indices)
    result = analysis.paired_bootstrap_comparison(
        btc,
        eth,
        block_length=8,
        resamples=100,
        confidence=0.95,
        seed=20260722,
    )

    assert calls == 100
    assert result["annualized_mean_delta"] == pytest.approx(
        analysis.annualized_mean(btc) - analysis.annualized_mean(eth)
    )
    assert result["annualized_sharpe_delta"] == pytest.approx(
        analysis.annualized_sharpe(btc) - analysis.annualized_sharpe(eth)
    )


def test_committed_result_records_single_rejected_candidate_and_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "rejected"
    assert result["method"]["fixed_base_configuration"] == {
        "max_position": 1.0,
        "min_position": 0.0,
        "momentum_lookback": 90,
        "reversal_lookback": 5,
        "reversal_weight": pytest.approx(0.3),
        "target_volatility": 0.5,
        "trend_weight": 0.7,
        "volatility_lookback": 30,
    }
    assert result["provenance"]["source_artifact_sha256"] == (
        "67bbf4136107a98bde8ddb118c6449d9db4da75b7eb7e9d3da82f822b156f43b"
    )
    assert set(result["markets"]) == {"BTC-USDT", "ETH-USDT"}
    assert all(market["observations"] == 2340 for market in result["markets"].values())
    assert all(market["passes"] is False for market in result["markets"].values())
