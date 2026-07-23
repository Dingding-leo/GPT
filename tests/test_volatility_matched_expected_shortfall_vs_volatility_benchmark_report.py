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

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = (
    REPOSITORY_ROOT
    / "reports"
    / "research"
    / "volatility-matched-expected-shortfall-vs-volatility-benchmark"
    / "analysis.py"
)
RESULT_PATH = ANALYSIS_PATH.with_name("result.json")
FIXTURE_DIR = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "okx_btc_usdt_oos_volatility_matched_es_20200111_20200219"
)
FIXTURE_PATH = FIXTURE_DIR / "returns.csv"
METADATA_PATH = FIXTURE_DIR / "metadata.json"
FIXTURE_SHA256 = "20a7125cafcf4c4b88275193b6afcce9d7ea570ba7d60402b3cab301bebb6503"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("volatility_matched_es_benchmark", ANALYSIS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_returns() -> tuple[np.ndarray, np.ndarray]:
    assert hashlib.sha256(FIXTURE_PATH.read_bytes()).hexdigest() == FIXTURE_SHA256
    metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    assert metadata["fixture_sha256"] == FIXTURE_SHA256
    assert metadata["provider"] == "OKX"
    assert metadata["instrument"] == "BTC-USDT"
    assert metadata["timeframe"] == "1Dutc"
    assert metadata["rows"] == 40

    frame = pd.read_csv(FIXTURE_PATH)
    return (
        frame["strategy_return"].to_numpy(dtype=float),
        frame["benchmark_volatility_targeted_long_return"].to_numpy(dtype=float),
    )


def _expected_shortfall(values: np.ndarray, tail_fraction: float) -> float:
    tail_count = math.ceil(len(values) * tail_fraction)
    return float(np.mean(np.sort(values)[:tail_count]))


def _write_artifact_fixture(artifact_dir: Path, payload: bytes) -> None:
    for market in ("BTC-USDT", "ETH-USDT"):
        market_dir = artifact_dir / market
        market_dir.mkdir(parents=True)
        (market_dir / "walk_forward_returns.csv").write_bytes(payload)


def test_volatility_matching_and_expected_shortfall_use_real_okx_returns() -> None:
    analysis = _load_analysis()
    strategy, benchmark = _fixture_returns()

    result = analysis.volatility_matched_expected_shortfall_delta(
        strategy,
        benchmark,
        tail_fraction=0.05,
    )

    expected_scale = float(np.std(strategy, ddof=1) / np.std(benchmark, ddof=1))
    matched_benchmark = benchmark * expected_scale
    expected_strategy_es = _expected_shortfall(strategy, 0.05)
    expected_benchmark_es = _expected_shortfall(matched_benchmark, 0.05)

    assert result["volatility_match_scale"] == pytest.approx(expected_scale)
    assert np.std(matched_benchmark, ddof=1) == pytest.approx(np.std(strategy, ddof=1))
    assert result["strategy_expected_shortfall"] == pytest.approx(expected_strategy_es)
    assert result["volatility_matched_benchmark_expected_shortfall"] == pytest.approx(
        expected_benchmark_es
    )
    assert result["observed_delta"] == pytest.approx(expected_strategy_es - expected_benchmark_es)


def test_bootstrap_recomputes_scale_for_each_paired_real_return_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    strategy, benchmark = _fixture_returns()
    sample_sets = (
        np.concatenate((np.arange(0, 20), np.arange(10, 30))),
        np.concatenate((np.arange(20, 40), np.arange(5, 25))),
    )
    samples = iter(sample_sets)
    monkeypatch.setattr(
        analysis,
        "moving_block_indices",
        lambda observation_count, block_length, rng: next(samples),
    )

    result = analysis.bootstrap_volatility_matched_expected_shortfall_delta(
        strategy,
        benchmark,
        tail_fraction=0.05,
        block_length=20,
        resamples=2,
        confidence=0.95,
        seed=17,
    )

    expected_deltas = []
    expected_scales = []
    for indices in sample_sets:
        sampled_strategy = strategy[indices]
        sampled_benchmark = benchmark[indices]
        scale = float(np.std(sampled_strategy, ddof=1) / np.std(sampled_benchmark, ddof=1))
        expected_scales.append(scale)
        expected_deltas.append(
            _expected_shortfall(sampled_strategy, 0.05)
            - _expected_shortfall(sampled_benchmark * scale, 0.05)
        )

    assert result["ci_lower"] == pytest.approx(np.quantile(expected_deltas, 0.025))
    assert result["ci_upper"] == pytest.approx(np.quantile(expected_deltas, 0.975))
    assert result["bootstrap_scale_ci_lower"] == pytest.approx(np.quantile(expected_scales, 0.025))
    assert result["bootstrap_scale_ci_upper"] == pytest.approx(np.quantile(expected_scales, 0.975))


def test_moving_blocks_are_deterministic_and_contiguous() -> None:
    analysis = _load_analysis()
    first = analysis.moving_block_indices(40, 10, np.random.default_rng(20260723))
    second = analysis.moving_block_indices(40, 10, np.random.default_rng(20260723))

    np.testing.assert_array_equal(first, second)
    assert len(first) == 40
    assert int(first.min()) >= 0
    assert int(first.max()) < 40
    for start in range(0, 40, 10):
        np.testing.assert_array_equal(np.diff(first[start : start + 10]), np.ones(9))


def test_result_records_single_rejected_candidate_and_bound_provenance() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["settings"]["volatility_scale_recomputed_per_resample"] is True
    assert result["provenance"]["source_artifact_id"] == 8559031387
    assert result["provenance"]["source_artifact_sha256"] == (
        "9d7f5c91ac46c8a3d5a3b0d34f569936bd70bc4197161ae5d977c2c6730e0c04"
    )
    assert result["markets"]["BTC-USDT"]["observations"] == 2385
    assert result["markets"]["ETH-USDT"]["observations"] == 2385
    assert result["markets"]["BTC-USDT"]["observed_delta"] == pytest.approx(-0.0009550359305191547)
    assert result["markets"]["ETH-USDT"]["observed_delta"] == pytest.approx(-0.004179768015039168)
    assert result["markets"]["ETH-USDT"]["ci_upper"] < 0.0


def test_build_result_verifies_both_retained_payloads_before_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    artifact_dir = tmp_path / "artifact"
    payload = FIXTURE_PATH.read_bytes()
    _write_artifact_fixture(artifact_dir, payload)
    for market in analysis.MARKETS:
        monkeypatch.setitem(analysis.EXPECTED_RETURN_FILE_SHA256, market, FIXTURE_SHA256)
    monkeypatch.setattr(analysis, "RESAMPLES", 1)

    read_counts = {market: 0 for market in analysis.MARKETS}
    events: list[tuple[str, str]] = []
    verified_payload_ids: dict[str, int] = {}
    parsed_payload_ids: dict[str, int] = {}
    original_read_bytes = Path.read_bytes
    original_verify = analysis.verify_return_payload_sha256
    original_load = analysis.load_returns

    def counted_read_bytes(path: Path) -> bytes:
        market = path.parent.name
        if market in read_counts and path.name == "walk_forward_returns.csv":
            read_counts[market] += 1
        return original_read_bytes(path)

    def recording_verify(return_payload: bytes, market: str) -> str:
        events.append(("verify", market))
        verified_payload_ids[market] = id(return_payload)
        return original_verify(return_payload, market)

    def recording_load(return_payload: bytes) -> pd.DataFrame:
        market = analysis.MARKETS[len(parsed_payload_ids)]
        events.append(("parse", market))
        parsed_payload_ids[market] = id(return_payload)
        return original_load(return_payload)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)
    monkeypatch.setattr(analysis, "verify_return_payload_sha256", recording_verify)
    monkeypatch.setattr(analysis, "load_returns", recording_load)

    result = analysis.build_result(artifact_dir)

    assert events[:2] == [("verify", "BTC-USDT"), ("verify", "ETH-USDT")]
    assert read_counts == {"BTC-USDT": 1, "ETH-USDT": 1}
    assert parsed_payload_ids == verified_payload_ids
    assert set(result["markets"]) == set(analysis.MARKETS)


@pytest.mark.parametrize("corrupt_market", ("BTC-USDT", "ETH-USDT"))
def test_digest_mismatch_is_rejected_before_parse_bootstrap_or_output(
    corrupt_market: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    artifact_dir = tmp_path / "artifact"
    payload = FIXTURE_PATH.read_bytes()
    _write_artifact_fixture(artifact_dir, payload)
    for market in analysis.MARKETS:
        monkeypatch.setitem(analysis.EXPECTED_RETURN_FILE_SHA256, market, FIXTURE_SHA256)

    corrupt_path = artifact_dir / corrupt_market / "walk_forward_returns.csv"
    corrupt_path.write_bytes(payload + b"\n")
    monkeypatch.setattr(
        analysis,
        "load_returns",
        lambda return_payload: pytest.fail("unverified payload must not be parsed"),
    )
    monkeypatch.setattr(
        analysis,
        "bootstrap_volatility_matched_expected_shortfall_delta",
        lambda *args, **kwargs: pytest.fail("bootstrap must not run after digest mismatch"),
    )
    output = tmp_path / "result.json"
    monkeypatch.setattr(
        analysis,
        "parse_args",
        lambda: argparse.Namespace(artifact_dir=str(artifact_dir), output=str(output)),
    )

    with pytest.raises(ValueError, match=rf"{corrupt_market} return file SHA-256 mismatch"):
        analysis.main()

    assert not output.exists()
