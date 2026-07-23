from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "reports" / "research" / "ex_ante_risk_budget_overlay" / "analysis.py"
RESULT_PATH = ROOT / "reports" / "research" / "ex_ante_risk_budget_overlay" / "result.json"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "okx" / "btc_eth_oos_20200111_20200219"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("ex_ante_risk_budget_overlay", ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load risk-budget analysis")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_returns() -> pd.Series:
    metadata = json.loads((FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    path = FIXTURE_DIR / "btc_usdt_returns.csv"
    payload = path.read_bytes()
    details = metadata["instruments"]["BTC-USDT"]
    assert hashlib.sha256(payload).hexdigest() == details["fixture_sha256"]
    frame = pd.read_csv(path)
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True, errors="raise"))
    assert len(frame) == details["observations"] == 40
    return pd.Series(
        frame["strategy_return"].to_numpy(dtype=float),
        index=timestamps,
        name="observed_return",
    )


def test_fold_scale_uses_only_prior_observed_real_okx_returns() -> None:
    analysis = _load_analysis()
    observed = _fixture_returns()
    selection = pd.concat([observed] * 19, ignore_index=True).iloc[: analysis.SELECTION_BARS]

    result = analysis.estimate_fold_scale(selection, 0.10)
    assert result["estimated_annualized_gross_strategy_volatility"] == pytest.approx(
        0.14701525932865525
    )
    assert result["applied_scale"] == pytest.approx(0.6802015005561308)

    future_changed = pd.concat([selection, observed.iloc[:10] * -3.0], ignore_index=True)
    changed = analysis.estimate_fold_scale(
        future_changed.iloc[: analysis.SELECTION_BARS],
        0.10,
    )
    assert changed == result


def test_nav_is_recomputed_from_real_observed_strategy_returns() -> None:
    analysis = _load_analysis()
    observed = _fixture_returns()
    frame = pd.DataFrame({"strategy_return": observed})

    rebuilt = analysis.recompute_nav(frame)

    expected = (1.0 + observed).cumprod()
    pd.testing.assert_series_equal(rebuilt["nav"], expected, check_names=False)
    assert rebuilt["nav"].iloc[-1] == pytest.approx(float(expected.iloc[-1]))


def test_cli_writes_fresh_analysis_output_without_loading_committed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    expected = {"recomputed": True, "candidate_accounting": {"searched": 3}}
    output = tmp_path / "result.json"
    monkeypatch.setattr(analysis, "analyze", lambda artifact_dir: expected)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(ANALYSIS_PATH),
            "--artifact-dir",
            str(tmp_path / "artifact"),
            "--output",
            str(output),
        ],
    )

    assert analysis.main() == 0
    assert json.loads(output.read_text(encoding="utf-8")) == expected


def test_committed_result_discloses_all_candidates_and_rejection() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    assert result["candidate_accounting"] == {
        "passed": 0,
        "passed_candidates": [],
        "rejected": 3,
        "searched": 3,
    }
    assert result["verdict"] == "rejected"
    assert result["architecture_freeze_eligible"] is False
    assert result["live_eligible"] is False
    assert set(result["candidates"]) == {"15pct", "20pct", "25pct"}
    assert result["method"]["sealed_market_data_used"] is False
    assert result["method"]["baseline_exchange_fee_bps_one_way"] == 5.0
    assert result["method"]["all_in_cost_sensitivities_bps"] == [5.0, 7.5, 10.0, 15.0]
    assert result["method"]["seed_rule"].startswith("sha256(")
    assert "family-v2" in result["canonical_signature"]


def test_headline_metrics_bootstrap_and_gate_failures_are_locked() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    candidate = result["candidates"]["15pct"]
    btc = candidate["markets"]["BTC-USDT"]
    eth = candidate["markets"]["ETH-USDT"]

    assert btc["metrics_5bps"]["total_return"] == pytest.approx(1.0353874293409033)
    assert btc["metrics_5bps"]["sharpe"] == pytest.approx(0.7732571546331812)
    assert btc["metrics_5bps"]["max_drawdown"] == pytest.approx(-0.19001864495122633)
    assert btc["fold_stability"]["profitable_folds"] == 13
    assert btc["bootstrap_vs_volatility_targeted_long"]["sharpe_delta"]["lower"] == pytest.approx(
        -0.6093122278751271
    )

    assert eth["metrics_5bps"]["total_return"] == pytest.approx(0.4980041788913707)
    assert eth["metrics_5bps"]["sharpe"] == pytest.approx(0.446250986874224)
    assert eth["metrics_5bps"]["max_drawdown"] == pytest.approx(-0.2234003485615621)
    assert eth["fold_stability"]["profitable_folds"] == 17
    assert eth["bootstrap_vs_volatility_targeted_long"]["calmar_delta"]["lower"] == pytest.approx(
        -1.7481465306439323
    )

    assert candidate["joint_gates"]["development_benchmark_relative_risk_adjusted"] == "fail"
    assert candidate["joint_gates"]["fold_stability"] == "fail"
    assert candidate["joint_gates"]["execution_delay_robustness"] == "fail"
    assert candidate["joint_gates"]["turnover_and_5_7.5_10_15bps_viability"] == "pass"
    assert candidate["joint_gates"]["parameter_neighbourhood_stability"] == "pass"
    assert candidate["joint_gates"]["tail_risk"] == "pass"
