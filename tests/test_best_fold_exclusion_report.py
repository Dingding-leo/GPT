from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "best-fold-exclusion" / "analysis.py"
)
RESULT_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "best-fold-exclusion" / "result.json"
)
FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc_eth_oos_20200111_20200219"
    / "btc_usdt_returns.csv"
)
FIXTURE_SHA256 = "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587"

SPEC = importlib.util.spec_from_file_location("best_fold_exclusion_analysis", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to import analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _real_returns() -> np.ndarray:
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == FIXTURE_SHA256
    frame = pd.read_csv(FIXTURE_PATH)
    return pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(dtype=float)


def test_best_fold_exclusion_uses_compounded_return_and_removes_one_fold() -> None:
    values = _real_returns()
    frame = pd.DataFrame(
        {
            "fold": np.repeat([1, 2], 20),
            "strategy_return": values,
        }
    )
    expected_totals = {
        fold_id: float(np.prod(1.0 + fold_values) - 1.0)
        for fold_id, fold_values in ((1, values[:20]), (2, values[20:]))
    }
    expected_best = max(expected_totals, key=lambda fold_id: (expected_totals[fold_id], -fold_id))

    best_fold, best_total, remaining = analysis.exclude_best_fold(frame)

    assert best_fold == expected_best
    assert best_total == expected_totals[expected_best]
    assert len(remaining) == 1
    expected_remaining = values[20:] if expected_best == 1 else values[:20]
    np.testing.assert_array_equal(remaining[0], expected_remaining)


def test_fold_block_bootstrap_samples_complete_observed_folds_deterministically() -> None:
    values = _real_returns()
    folds = (values[:20], values[20:])
    seed = 20260723
    resamples = 25

    observed = analysis.fold_block_mean_distribution(
        folds,
        resamples=resamples,
        annualization=365,
        seed=seed,
    )

    rng = np.random.default_rng(seed)
    fold_sums = np.asarray([fold.sum() for fold in folds], dtype=float)
    expected = np.empty(resamples, dtype=float)
    for index in range(resamples):
        selected = rng.integers(0, len(folds), size=len(folds))
        expected[index] = float(fold_sums[selected].sum()) / len(values) * 365

    np.testing.assert_array_equal(observed, expected)


def test_committed_result_records_single_rejected_candidate() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {
        "candidate_count": 1,
        "candidates_passed": 0,
        "candidates_rejected": 1,
        "searched_alternatives": [],
    }
    assert result["verdict"] == "rejected"
    assert result["markets"]["BTC-USDT"]["excluded_best_fold"] == 4
    assert result["markets"]["ETH-USDT"]["excluded_best_fold"] == 4
    assert result["markets"]["BTC-USDT"]["remaining_observations"] == 2250
    assert result["markets"]["ETH-USDT"]["remaining_observations"] == 2250
    assert result["markets"]["BTC-USDT"]["passes"] is False
    assert result["markets"]["ETH-USDT"]["passes"] is False
    assert result["failure_reasons"] == [
        "BTC-USDT best-fold-excluded annualized mean lower confidence bound is not positive",
        "ETH-USDT best-fold-excluded annualized mean lower confidence bound is not positive",
    ]
