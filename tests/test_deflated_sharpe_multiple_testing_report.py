from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
from statistics import NormalDist

import pandas as pd
import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_ANALYSIS_PATH = (
    _REPOSITORY_ROOT / "reports" / "research" / "deflated-sharpe-multiple-testing" / "analysis.py"
)
_SPEC = importlib.util.spec_from_file_location("deflated_sharpe_multiple_testing", _ANALYSIS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"unable to load analysis module from {_ANALYSIS_PATH}")
analysis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis)

_FIXTURE_DIR = _REPOSITORY_ROOT / "tests" / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"
_RESULT_PATH = (
    _REPOSITORY_ROOT / "reports" / "research" / "deflated-sharpe-multiple-testing" / "result.json"
)


def _fixture_returns() -> pd.Series:
    path = _FIXTURE_DIR / "btc_usdt_returns.csv"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587"
    )
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["timeframe"] == "1Dutc"
    assert metadata["instruments"]["BTC-USDT"]["observations"] == 40
    return pd.read_csv(path)["strategy_return"]


def test_deflated_sharpe_matches_reference_on_real_okx_returns() -> None:
    returns = _fixture_returns()
    result = analysis.deflated_sharpe_statistics(returns, effective_trials=27)

    values = returns.to_numpy(dtype=float)
    observed = float(values.mean() / values.std(ddof=0))
    skewness = float(returns.skew())
    raw_kurtosis = float(returns.kurt() + 3.0)
    normal = NormalDist()
    expected_maximum_z = (1.0 - analysis.EULER_MASCHERONI) * normal.inv_cdf(
        1.0 - 1.0 / 27.0
    ) + analysis.EULER_MASCHERONI * normal.inv_cdf(1.0 - 1.0 / (27.0 * math.e))
    benchmark = expected_maximum_z / math.sqrt(len(values) - 1)
    denominator = math.sqrt(1.0 - skewness * observed + ((raw_kurtosis - 1.0) / 4.0) * observed**2)
    expected_z = (observed - benchmark) * math.sqrt(len(values) - 1) / denominator

    assert result["observed_daily_sharpe"] == pytest.approx(observed, abs=1e-15)
    assert result["sample_skewness"] == pytest.approx(skewness, abs=1e-15)
    assert result["sample_raw_kurtosis"] == pytest.approx(raw_kurtosis, abs=1e-15)
    assert result["expected_maximum_null_z"] == pytest.approx(expected_maximum_z, abs=1e-15)
    assert result["deflated_sharpe_z"] == pytest.approx(expected_z, abs=1e-15)
    assert result["deflated_sharpe_probability"] == pytest.approx(normal.cdf(expected_z), abs=1e-15)


def test_multiple_testing_penalty_increases_on_real_okx_returns() -> None:
    returns = _fixture_returns()
    two_trials = analysis.deflated_sharpe_statistics(returns, effective_trials=2)
    twenty_seven_trials = analysis.deflated_sharpe_statistics(returns, effective_trials=27)

    assert (
        twenty_seven_trials["deflated_benchmark_daily_sharpe"]
        > two_trials["deflated_benchmark_daily_sharpe"]
    )
    assert (
        twenty_seven_trials["deflated_sharpe_probability"]
        < two_trials["deflated_sharpe_probability"]
    )


def test_committed_result_records_complete_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"] == analysis.SIGNATURE
    assert result["candidate_accounting"] == {"passed": 0, "rejected": 1, "searched": 1}
    assert result["verdict"] == "rejected"
    assert result["method"]["effective_trials"] == 27
    assert result["provenance"]["source_artifact_sha256"] == (
        "e547d220d6f1f1649038387471c3cf9fef6da6d9f71d793f80ee2b0d114bcca4"
    )
    assert set(result["markets"]) == {"BTC-USDT", "ETH-USDT"}
    assert all(not market["passes"] for market in result["markets"].values())
    assert all(
        market["deflated_sharpe_probability"] < analysis.PASS_PROBABILITY
        for market in result["markets"].values()
    )
