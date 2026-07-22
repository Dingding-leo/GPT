from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "fold-boundary-exclusion" / "analysis.py"
)
RESULT_PATH = (
    REPOSITORY_ROOT / "reports" / "research" / "fold-boundary-exclusion" / "result.json"
)
FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "okx"
    / "btc_eth_oos_20200111_20200219"
    / "btc_usdt_returns.csv"
)
FIXTURE_SHA256 = "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587"

SPEC = importlib.util.spec_from_file_location("fold_boundary_exclusion_analysis", ANALYSIS_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"unable to import analysis module from {ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _real_returns() -> np.ndarray:
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == FIXTURE_SHA256
    frame = pd.read_csv(FIXTURE_PATH)
    return pd.to_numeric(frame["strategy_return"], errors="raise").to_numpy(dtype=float)


def test_fold_boundary_exclusion_removes_only_each_fold_first_observation() -> None:
    values = _real_returns()
    frame = pd.DataFrame(
        {
            "fold": np.repeat([1, 2], 20),
            "strategy_return": values,
        }
    )

    segments = analysis.fold_interior_segments(frame)

    assert len(segments) == 2
    assert all(len(segment) == 19 for segment in segments)
    np.testing.assert_array_equal(
        np.concatenate(segments),
        np.concatenate([values[1:20], values[21:40]]),
    )


def test_segmented_bootstrap_is_seeded_on_observed_real_returns() -> None:
    values = _real_returns()
    segments = (values[:20], values[20:])

    first = analysis.segmented_moving_block_mean_distribution(
        segments,
        block_length=10,
        resamples=25,
        annualization=365,
        seed=20260722,
    )
    repeated = analysis.segmented_moving_block_mean_distribution(
        segments,
        block_length=10,
        resamples=25,
        annualization=365,
        seed=20260722,
    )
    different_seed = analysis.segmented_moving_block_mean_distribution(
        segments,
        block_length=10,
        resamples=25,
        annualization=365,
        seed=20260723,
    )

    np.testing.assert_array_equal(first, repeated)
    assert not np.array_equal(first, different_seed)


def test_segmented_bootstrap_never_combines_fold_segments(monkeypatch) -> None:
    values = _real_returns()
    segments = (values[:20], values[20:])
    observed_ids: list[int] = []

    def record_segment(
        segment: np.ndarray,
        *,
        block_length: int,
        rng: np.random.Generator,
    ) -> np.ndarray:
        assert block_length == 20
        assert isinstance(rng, np.random.Generator)
        observed_ids.append(id(segment))
        return segment.copy()

    monkeypatch.setattr(analysis, "resample_segment_non_circular", record_segment)
    analysis.segmented_moving_block_mean_distribution(
        segments,
        block_length=20,
        resamples=3,
        annualization=365,
        seed=20260722,
    )

    assert observed_ids == [id(segments[0]), id(segments[1])] * 3


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
    assert result["markets"]["BTC-USDT"]["passes"] is True
    assert result["markets"]["ETH-USDT"]["passes"] is False
    assert result["markets"]["BTC-USDT"]["boundary_observations_removed"] == 26
    assert result["markets"]["ETH-USDT"]["interior_observations"] == 2314
    assert result["failure_reasons"] == [
        "ETH-USDT fold-interior annualized mean lower confidence bound is not positive"
    ]
