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
    REPOSITORY_ROOT / "reports" / "research" / "benchmark-relative-fold-breadth" / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = (
    REPOSITORY_ROOT / "tests" / "fixtures" / "okx" / "btc_usdt_relative_folds_20200111_20201006"
)
FIXTURE_PATH = FIXTURE_DIR / "btc_usdt_relative_folds.csv"
METADATA_PATH = FIXTURE_DIR / "metadata.json"

SPEC = importlib.util.spec_from_file_location("benchmark_relative_fold_breadth", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_okx_fixture_provenance_and_fold_compounding() -> None:
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert _sha256(FIXTURE_PATH) == metadata["fixture_sha256"]
    assert metadata["provider"] == "OKX"
    assert metadata["instrument"] == "BTC-USDT"
    assert metadata["timeframe"] == "1Dutc"
    assert metadata["observations"] == 270
    assert metadata["folds"] == [1, 2, 3]

    source = pd.read_csv(FIXTURE_PATH)
    validated, folds = analysis.load_complete_fold_deltas(
        FIXTURE_PATH,
        expected_complete_folds=3,
    )
    assert len(validated) == len(source) == 270
    assert folds["fold"].tolist() == [1, 2, 3]

    expected_deltas = []
    for fold_id, fold in source.groupby("fold", sort=True):
        assert len(fold) == 90
        strategy = float(np.prod(1.0 + fold["strategy_return"].to_numpy()) - 1.0)
        benchmark = float(
            np.prod(1.0 + fold["benchmark_volatility_targeted_long_return"].to_numpy()) - 1.0
        )
        expected_deltas.append(strategy - benchmark)
        assert int(fold_id) in (1, 2, 3)

    np.testing.assert_allclose(folds["relative_return_delta"], expected_deltas, rtol=0, atol=0)


def test_oversized_trailing_fold_is_rejected_before_exclusion(tmp_path: Path) -> None:
    source = pd.read_csv(FIXTURE_PATH)
    structural_copy = pd.concat(
        [
            source.loc[source["fold"] == 1].head(10),
            source.loc[source["fold"] == 2].head(10),
            source.loc[source["fold"] == 3].head(11),
        ],
        ignore_index=True,
    )
    path = tmp_path / "oversized-trailing-fold.csv"
    structural_copy.to_csv(path, index=False)

    with pytest.raises(ValueError, match="trailing incomplete fold must be shorter"):
        analysis.load_complete_fold_deltas(
            path,
            expected_complete_folds=2,
            expected_fold_observations=10,
        )


def test_moving_fold_blocks_are_deterministic_on_observed_relative_returns() -> None:
    _, folds = analysis.load_complete_fold_deltas(
        FIXTURE_PATH,
        expected_complete_folds=3,
    )
    relative_returns = folds["relative_return_delta"].to_numpy(dtype=float)
    first = analysis.moving_block_outperformance_share(
        relative_returns,
        block_length=2,
        resamples=200,
        confidence=0.95,
        seed=20260723,
    )
    second = analysis.moving_block_outperformance_share(
        relative_returns,
        block_length=2,
        resamples=200,
        confidence=0.95,
        seed=20260723,
    )

    assert first == second
    assert first["complete_folds"] == 3
    assert 0.0 <= first["confidence_lower"] <= first["confidence_upper"] <= 1.0


def test_committed_result_records_one_rejected_candidate_and_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["verdict"] == "reject"
    assert result["markets"]["BTC-USDT"]["outperforming_folds"] == 12
    assert result["markets"]["ETH-USDT"]["outperforming_folds"] == 9
    assert result["provenance"]["source_artifact_sha256"] == (
        "79cd3100c2f41d42d4fc61c1e63e765c5ec4c6b9645457c9d24469121c88b1be"
    )
