from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).parents[1]
_ANALYSIS_PATH = (
    _ROOT / "reports/research/expected-shortfall-vs-buy-and-hold/analysis.py"
)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")
_FIXTURE_PATH = _ROOT / "tests/fixtures/okx_btc_usdt_oos_returns_20200111_20200219.csv"
_METADATA_PATH = _FIXTURE_PATH.with_suffix(".metadata.json")

_SPEC = importlib.util.spec_from_file_location(
    "expected_shortfall_analysis", _ANALYSIS_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_ANALYSIS = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_ANALYSIS)


def _fixture() -> pd.DataFrame:
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    assert (
        hashlib.sha256(_FIXTURE_PATH.read_bytes()).hexdigest()
        == metadata["fixture_sha256"]
    )
    frame = pd.read_csv(_FIXTURE_PATH)
    assert len(frame) == metadata["rows"]
    assert frame["timestamp"].iloc[0] == metadata["start"]
    assert frame["timestamp"].iloc[-1] == metadata["end"]
    return frame


def _independent_expected_shortfall(values: np.ndarray, tail_fraction: float) -> float:
    observed = np.sort(np.asarray(values, dtype=float))
    tail_count = math.ceil(observed.size * tail_fraction)
    return float(observed[:tail_count].mean())


def test_real_okx_fixture_and_expected_shortfall_formula() -> None:
    metadata = json.loads(_METADATA_PATH.read_text(encoding="utf-8"))
    frame = _fixture()

    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["bar"] == "1Dutc"
    for column in ("strategy_return", "benchmark_buy_and_hold_return"):
        values = frame[column].to_numpy(dtype=float)
        assert _ANALYSIS.expected_shortfall(values, 0.05) == pytest.approx(
            _independent_expected_shortfall(values, 0.05)
        )


def test_paired_block_bootstrap_is_deterministic_and_contiguous() -> None:
    frame = _fixture()
    strategy = frame["strategy_return"].to_numpy(dtype=float)
    benchmark = frame["benchmark_buy_and_hold_return"].to_numpy(dtype=float)
    kwargs = {
        "tail_fraction": 0.05,
        "block_length": 10,
        "resamples": 200,
        "confidence": 0.95,
        "seed": 2026072313,
    }

    first = _ANALYSIS.bootstrap_expected_shortfall_delta(strategy, benchmark, **kwargs)
    second = _ANALYSIS.bootstrap_expected_shortfall_delta(strategy, benchmark, **kwargs)
    assert first == second
    assert first["observed_delta"] == pytest.approx(
        _independent_expected_shortfall(strategy, 0.05)
        - _independent_expected_shortfall(benchmark, 0.05)
    )

    indices = _ANALYSIS.moving_block_indices(40, 10, np.random.default_rng(17))
    assert np.all(np.diff(indices.reshape(4, 10), axis=1) == 1)
    assert indices.min() >= 0
    assert indices.max() < 40


def test_timestamp_validation_rejects_timezone_naive_copy(tmp_path: Path) -> None:
    frame = _fixture().copy()
    frame["timestamp"] = frame["timestamp"].str.replace("+00:00", "", regex=False)
    malformed = tmp_path / "timezone-naive.csv"
    frame.to_csv(malformed, index=False)

    with pytest.raises(ValueError, match="explicit timezone offset"):
        _ANALYSIS.load_returns(malformed)


def test_artifact_hash_mismatch_fails_before_analysis_or_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir = tmp_path / "artifact"
    original_sha256 = hashlib.sha256(_FIXTURE_PATH.read_bytes()).hexdigest()
    for market in _ANALYSIS.MARKETS:
        market_dir = artifact_dir / market
        market_dir.mkdir(parents=True)
        (market_dir / "walk_forward_returns.csv").write_bytes(
            _FIXTURE_PATH.read_bytes()
        )

    altered = _fixture().copy()
    altered.loc[0, "strategy_return"] = (
        float(altered.loc[0, "strategy_return"]) + 0.0001
    )
    altered.to_csv(artifact_dir / "BTC-USDT" / "walk_forward_returns.csv", index=False)

    monkeypatch.setattr(
        _ANALYSIS,
        "EXPECTED_RETURN_FILE_SHA256",
        {market: original_sha256 for market in _ANALYSIS.MARKETS},
    )

    def fail_if_analyzed(*args: object, **kwargs: object) -> dict[str, float]:
        raise AssertionError("hash verification must happen before analysis")

    monkeypatch.setattr(
        _ANALYSIS, "bootstrap_expected_shortfall_delta", fail_if_analyzed
    )
    output = tmp_path / "result" / "result.json"
    monkeypatch.setattr(
        _ANALYSIS,
        "parse_args",
        lambda: argparse.Namespace(artifact_dir=str(artifact_dir), output=str(output)),
    )

    with pytest.raises(ValueError, match="BTC-USDT return file SHA-256 mismatch"):
        _ANALYSIS.main()
    assert not output.parent.exists()


def test_committed_result_records_complete_supported_candidate() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == _ANALYSIS.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {"searched": 1, "passed": 1, "rejected": 0}
    assert result["verdict"] == "supported"
    assert result["markets"]["BTC-USDT"]["passed"] is True
    assert result["markets"]["ETH-USDT"]["passed"] is True
    assert result["provenance"]["source_artifact_sha256"] == (
        "60eeccc96a8baee381cde8e49c519543ce274bfcb48af4fa6bcb016ebc93aaf2"
    )
    assert result["markets"]["BTC-USDT"]["return_file_sha256"] == (
        "ebf2e4cc63e6b21a2d89420e2c2dd5b3517179baacfd12931f75fb0d99bdd2ce"
    )
    assert result["markets"]["ETH-USDT"]["return_file_sha256"] == (
        "bd4fbc471d506069c01b86b39f7726b1bd05752bfd64e75b7d677d2d7f473047"
    )
    assert result["provenance"]["expected_return_file_sha256"] == (
        _ANALYSIS.EXPECTED_RETURN_FILE_SHA256
    )
    assert result["markets"]["BTC-USDT"]["tail_observations"] == 120
    assert result["markets"]["ETH-USDT"]["tail_observations"] == 120
