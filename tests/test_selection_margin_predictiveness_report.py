from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

_REPORT_DIR = Path(__file__).parents[1] / "reports" / "research" / "selection-margin-predictiveness"
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"
_RESULT_PATH = _REPORT_DIR / "result.json"
_SPEC = importlib.util.spec_from_file_location("selection_margin_predictiveness", _ANALYSIS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {_ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis)


def _result() -> dict[str, object]:
    return json.loads(_RESULT_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("market", ["BTC-USDT", "ETH-USDT"])
def test_persisted_fold_pairs_recompute_point_spearman(market: str) -> None:
    result = _result()
    market_result = result["markets"][market]
    evidence = market_result["fold_inputs"]

    assert evidence["folds"] == list(range(1, 27))
    gaps = np.array(evidence["runner_up_score_gaps"], dtype=float)
    returns = np.array(evidence["test_total_returns"], dtype=float)
    recomputed = analysis.spearman_rank_correlation(gaps, returns)
    assert recomputed == pytest.approx(market_result["point_spearman"], abs=1e-15)


def test_fold_bootstrap_is_deterministic_and_pair_preserving() -> None:
    result = _result()
    evidence = result["markets"]["BTC-USDT"]["fold_inputs"]
    fold_evidence = [
        {
            "runner_up_score_gap": gap,
            "test_total_return": total_return,
        }
        for gap, total_return in zip(
            evidence["runner_up_score_gaps"],
            evidence["test_total_returns"],
            strict=True,
        )
    ]
    first = analysis.analyze_market(fold_evidence, seed=20260722)
    second = analysis.analyze_market(fold_evidence, seed=20260722)

    assert first == second
    assert first["fold_count"] == 26
    assert first["bootstrap"]["ci_lower"] < first["point_spearman"]
    assert first["bootstrap"]["ci_upper"] > first["point_spearman"]

    rng = np.random.default_rng(20260722)
    indices = analysis.moving_block_indices(26, rng)
    assert len(indices) == 26
    for block_start in range(0, 26, analysis.BLOCK_LENGTH):
        block = indices[block_start : block_start + analysis.BLOCK_LENGTH]
        if len(block) > 1:
            assert np.diff(block).tolist() == [1] * (len(block) - 1)


def test_result_locks_single_candidate_rejection_and_provenance() -> None:
    result = _result()
    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {
        "candidate_count": 1,
        "searched_alternatives": [],
    }
    assert result["data_provenance"]["artifact_id"] == 8515812291
    assert result["data_provenance"]["artifact_sha256"] == (
        "9d3cfe6e86ad93dc6ed068d2a69029a099abf7a07b05de6b9abfa79c7e7710e6"
    )
    assert result["method"]["block_length_folds"] == 9
    assert result["method"]["resamples"] == 2_000
    assert all(
        market["bootstrap"]["lower_bound_positive"] is False
        for market in result["markets"].values()
    )
    assert result["verdict"].startswith("rejected:")
