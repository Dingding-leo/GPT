from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "reports" / "research" / "ex_ante_risk_budget_overlay" / "analysis.py"
RESULT_PATH = ROOT / "reports" / "research" / "ex_ante_risk_budget_overlay" / "result.json"
FIXTURE_DIR = (
    ROOT
    / "tests"
    / "fixtures"
    / "okx_btc_usdt_risk_budget_20180111_20200111"
)


def _load_analysis():
    spec = importlib.util.spec_from_file_location("ex_ante_risk_budget_overlay", ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load risk-budget analysis")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture_prices() -> pd.Series:
    metadata = json.loads((FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    payload = (FIXTURE_DIR / "prices.csv").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == metadata["fixture_sha256"]
    frame = pd.read_csv(FIXTURE_DIR / "prices.csv")
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True, errors="raise"))
    assert len(frame) == metadata["observations"] == 731
    assert timestamps[0].isoformat() == "2018-01-11T00:00:00+00:00"
    assert timestamps[-1].isoformat() == "2020-01-11T00:00:00+00:00"
    return pd.Series(frame["close"].to_numpy(dtype=float), index=timestamps, name="close")


def test_fold_scale_uses_only_prior_730_real_okx_sessions() -> None:
    analysis = _load_analysis()
    prices = _fixture_prices()
    parameters = {
        "momentum_lookback": 90,
        "reversal_lookback": 10,
        "trend_weight": 0.85,
    }
    frame = analysis.candidate_frame(prices, parameters)
    selection = frame.iloc[: analysis.SELECTION_BARS]

    expected = {
        0.15: 0.6528538665900356,
        0.20: 0.8704718221200476,
        0.25: 1.0,
    }
    for risk_budget, expected_scale in expected.items():
        result = analysis.estimate_fold_scale(
            selection["gross_strategy_return"],
            risk_budget,
        )
        assert result["estimated_annualized_gross_strategy_volatility"] == pytest.approx(
            0.22976045280006527
        )
        assert result["applied_scale"] == pytest.approx(expected_scale)

    altered = prices.copy()
    altered.iloc[-1] *= 1.25
    altered_frame = analysis.candidate_frame(altered, parameters)
    altered_result = analysis.estimate_fold_scale(
        altered_frame.iloc[: analysis.SELECTION_BARS]["gross_strategy_return"],
        0.20,
    )
    assert altered_result["applied_scale"] == pytest.approx(expected[0.20])


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


def test_headline_metrics_and_gate_failures_are_locked() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    candidate = result["candidates"]["15pct"]
    btc = candidate["markets"]["BTC-USDT"]
    eth = candidate["markets"]["ETH-USDT"]

    assert btc["metrics_5bps"]["total_return"] == pytest.approx(1.0353874293409033)
    assert btc["metrics_5bps"]["sharpe"] == pytest.approx(0.7732571546331812)
    assert btc["metrics_5bps"]["max_drawdown"] == pytest.approx(-0.19001864495122633)
    assert btc["fold_stability"]["profitable_folds"] == 13

    assert eth["metrics_5bps"]["total_return"] == pytest.approx(0.4980041788913707)
    assert eth["metrics_5bps"]["sharpe"] == pytest.approx(0.446250986874224)
    assert eth["metrics_5bps"]["max_drawdown"] == pytest.approx(-0.2234003485615621)
    assert eth["fold_stability"]["profitable_folds"] == 17

    assert candidate["joint_gates"]["development_benchmark_relative_risk_adjusted"] == "fail"
    assert candidate["joint_gates"]["fold_stability"] == "fail"
    assert candidate["joint_gates"]["execution_delay_robustness"] == "fail"
    assert candidate["joint_gates"]["turnover_and_5_7.5_10_15bps_viability"] == "pass"
    assert candidate["joint_gates"]["parameter_neighbourhood_stability"] == "pass"
    assert candidate["joint_gates"]["tail_risk"] == "pass"
