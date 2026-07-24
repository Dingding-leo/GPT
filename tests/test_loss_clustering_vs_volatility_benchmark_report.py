from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ANALYSIS_PATH = _ROOT / "reports/research/loss-clustering-vs-volatility-benchmark/analysis.py"
_RESULT_PATH = _ROOT / "reports/research/loss-clustering-vs-volatility-benchmark/result.json"
_FIXTURE_DIR = _ROOT / "tests/fixtures/okx_btc_usdt_oos_loss_clustering_20200111_20200219"
_RETURNS_FIXTURE = _FIXTURE_DIR / "returns.csv"
_METADATA_FIXTURE = _FIXTURE_DIR / "metadata.json"

_spec = importlib.util.spec_from_file_location("loss_clustering_analysis", _ANALYSIS_PATH)
assert _spec is not None and _spec.loader is not None
analysis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(analysis)


def _real_fixture() -> pd.DataFrame:
    metadata = json.loads(_METADATA_FIXTURE.read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["market_type"] == "spot"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    assert hashlib.sha256(_RETURNS_FIXTURE.read_bytes()).hexdigest() == metadata["fixture_sha256"]
    frame = pd.read_csv(_RETURNS_FIXTURE)
    assert len(frame) == metadata["rows"]
    assert frame["timestamp"].iloc[0] == metadata["start"]
    assert frame["timestamp"].iloc[-1] == metadata["end"]
    return frame


def test_loss_clustering_probability_matches_real_okx_transition_counts() -> None:
    frame = _real_fixture()
    strategy = frame["strategy_return"].to_numpy(dtype=float)
    previous_loss = strategy[:-1] < 0.0
    consecutive_loss = previous_loss & (strategy[1:] < 0.0)

    observed = analysis.loss_clustering_probability(strategy)

    assert observed == pytest.approx(consecutive_loss.sum() / previous_loss.sum())
    assert analysis.loss_transition_counts(strategy) == (
        int(consecutive_loss.sum()),
        int(previous_loss.sum()),
    )


def test_paired_block_bootstrap_is_deterministic_and_excludes_sampled_joins() -> None:
    frame = _real_fixture()
    strategy = frame["strategy_return"].to_numpy(dtype=float)
    benchmark = frame["benchmark_volatility_targeted_long_return"].to_numpy(dtype=float)
    kwargs = {
        "block_length": 40,
        "resamples": 50,
        "confidence": 0.95,
        "seed": 17,
    }

    first = analysis.bootstrap_loss_clustering_delta(strategy, benchmark, **kwargs)
    second = analysis.bootstrap_loss_clustering_delta(strategy, benchmark, **kwargs)
    blocks = analysis.sampled_block_indices(40, 10, np.random.default_rng(17))

    assert first == second
    assert len(blocks) == 4
    assert all(np.all(np.diff(block) == 1) for block in blocks)
    assert sum(len(block) - 1 for block in blocks) == 36
    assert first["strategy_prior_loss_count"] > 0
    assert first["benchmark_prior_loss_count"] > 0


def test_sampled_blocks_avoid_singleton_tail() -> None:
    blocks = analysis.sampled_block_indices(41, 20, np.random.default_rng(23))

    assert sum(len(block) for block in blocks) == 41
    assert all(len(block) >= 2 for block in blocks)
    assert [len(block) for block in blocks] == [20, 19, 2]
    assert all(np.all(np.diff(block) == 1) for block in blocks)


def test_sampled_blocks_reject_unavoidable_singleton() -> None:
    with pytest.raises(ValueError, match="partitioned into sampled blocks"):
        analysis.sampled_block_indices(3, 2, np.random.default_rng(29))


def test_loader_rejects_timezone_naive_copy_before_metrics(tmp_path: Path) -> None:
    frame = _real_fixture()
    frame.loc[3, "timestamp"] = frame.loc[3, "timestamp"].removesuffix("+00:00")
    path = tmp_path / "timezone-naive-loss-clustering-copy.csv"
    frame.to_csv(path, index=False)

    with pytest.raises(ValueError, match="explicit timezone offset"):
        analysis.load_returns(path)


def test_committed_result_records_single_rejected_candidate_and_provenance() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["markets"]["BTC-USDT"]["passed"] is False
    assert result["markets"]["ETH-USDT"]["passed"] is False
    assert result["provenance"]["source_artifact_sha256"] == (
        "4dbb277373d818c84487f021a2c02f268e95714c8aaf6c70672f3cd068f3c7c3"
    )
    assert result["provenance"]["current_main_commit"] == (
        "546aa5034c61c6dd13262199eb52910add93f5a6"
    )
    assert result["markets"]["BTC-USDT"]["return_file_sha256"] == (
        "ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce"
    )
    assert result["markets"]["ETH-USDT"]["return_file_sha256"] == (
        "bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047"
    )
