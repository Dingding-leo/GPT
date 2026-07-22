from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "fold-positive-breadth" / "analysis.py"
)
RESULT_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "fold-positive-breadth" / "result.json"
)
FIXTURE_DIR = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
)

SPEC = importlib.util.spec_from_file_location("fold_positive_breadth_analysis", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def test_fold_compounding_uses_unchanged_real_okx_returns(tmp_path: Path) -> None:
    source = pd.read_csv(FIXTURE_DIR / "btc_usdt_returns.csv")
    source["fold"] = np.repeat(np.arange(1, 5), 10)
    copied = tmp_path / "real_btc_returns_with_fold_labels.csv"
    source.to_csv(copied, index=False)
    validated, fold_returns = analysis.load_fold_returns(copied)

    expected = []
    for fold in range(1, 5):
        values = validated.loc[validated["fold"] == fold, "strategy_return"].to_numpy()
        expected.append(float(np.prod(1.0 + values) - 1.0))

    np.testing.assert_array_equal(fold_returns, np.array(expected))


def test_complete_fold_moving_blocks_are_deterministic_and_contiguous(
    tmp_path: Path,
) -> None:
    source = pd.read_csv(FIXTURE_DIR / "btc_usdt_returns.csv")
    source["fold"] = np.repeat(np.arange(1, 5), 10)
    copied = tmp_path / "real_btc_returns_for_blocks.csv"
    source.to_csv(copied, index=False)
    _, fold_returns = analysis.load_fold_returns(copied)

    first = analysis.moving_block_positive_share(
        fold_returns,
        block_length=2,
        resamples=200,
        confidence=0.95,
        seed=12345,
    )
    second = analysis.moving_block_positive_share(
        fold_returns,
        block_length=2,
        resamples=200,
        confidence=0.95,
        seed=12345,
    )

    assert first == second
    assert first["folds"] == 4
    assert 0.0 <= first["confidence_lower"] <= first["confidence_upper"] <= 1.0


def test_committed_result_has_one_rejected_candidate_and_verified_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "reject"
    assert result["markets"]["BTC-USDT"]["positive_folds"] == 12
    assert result["markets"]["ETH-USDT"]["positive_folds"] == 16
    assert result["provenance"]["source_artifact_sha256"] == (
        "d0e890b3aeefbff8420f6f8dbfcb7be6cf332839b206bde5b64566ac1b1600af"
    )
