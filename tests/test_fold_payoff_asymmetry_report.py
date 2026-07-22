from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "fold-payoff-asymmetry" / "analysis.py"
)
RESULT_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "fold-payoff-asymmetry" / "result.json"
)
FIXTURE_DIR = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
)

SPEC = importlib.util.spec_from_file_location("fold_payoff_asymmetry_analysis", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _real_fixture_fold_returns(tmp_path: Path) -> np.ndarray:
    source = pd.read_csv(FIXTURE_DIR / "btc_usdt_returns.csv")
    source["fold"] = np.repeat(np.arange(1, 5), 10)
    copied = tmp_path / "real_btc_returns_with_fold_labels.csv"
    source.to_csv(copied, index=False)
    _, fold_returns = analysis.load_fold_returns(copied)
    return fold_returns


def test_fold_payoff_ratio_uses_compounded_real_okx_fold_returns(tmp_path: Path) -> None:
    fold_returns = _real_fixture_fold_returns(tmp_path)

    positive = float(fold_returns[fold_returns > 0.0].sum())
    negative = float(-fold_returns[fold_returns < 0.0].sum())
    expected = positive / negative

    assert analysis.fold_payoff_ratio(fold_returns) == pytest.approx(expected, rel=0, abs=1e-15)


def test_complete_fold_payoff_blocks_are_deterministic(tmp_path: Path) -> None:
    fold_returns = _real_fixture_fold_returns(tmp_path)

    first = analysis.moving_block_payoff_ratio(
        fold_returns,
        block_length=2,
        resamples=200,
        confidence=0.95,
        seed=12345,
    )
    second = analysis.moving_block_payoff_ratio(
        fold_returns,
        block_length=2,
        resamples=200,
        confidence=0.95,
        seed=12345,
    )

    assert first == second
    assert first["folds"] == 4
    assert first["positive_folds"] + first["negative_folds"] + first["zero_folds"] == 4
    assert 0.0 <= first["confidence_lower"] <= first["confidence_upper"]
    assert 0.0 <= first["probability_ratio_above_one"] <= 1.0


def test_committed_result_has_one_rejected_candidate_and_exact_point_ratios() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "reject"
    assert result["provenance"]["source_artifact_sha256"] == (
        "83eb247b7d848ddc61ebbb914e937268af0352ed1cbb11371877e6d947de1fb3"
    )

    for market in analysis.MARKETS:
        statistics = result["markets"][market]
        fold_returns = np.asarray(statistics["fold_returns"], dtype=float)
        assert statistics["fold_payoff_ratio"] == pytest.approx(
            analysis.fold_payoff_ratio(fold_returns), rel=0, abs=1e-15
        )
        assert statistics["confidence_lower"] <= 1.0
