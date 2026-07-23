from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_PATH = ROOT / "reports" / "research" / "prior-volume-capacity-gate" / "analysis.py"
RESULT_PATH = ROOT / "reports" / "research" / "prior-volume-capacity-gate" / "result.json"
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "okx" / "btc_capacity_20191212_20200219"


def _load_analysis():
    spec = importlib.util.spec_from_file_location("prior_volume_capacity_gate", ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load capacity analysis")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture() -> pd.DataFrame:
    path = FIXTURE_DIR / "returns_and_volume.csv"
    metadata = json.loads((FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["provider"] == "OKX"
    assert metadata["instrument_id"] == "BTC-USDT"
    assert metadata["timeframe"] == "1Dutc"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == metadata["fixture_sha256"]
    frame = pd.read_csv(path)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True, errors="raise"))
    assert len(frame) == metadata["observations"] == 70
    return frame


def test_capacity_formula_uses_only_prior_real_okx_quote_volume() -> None:
    analysis = _load_analysis()
    fixture = _fixture()
    snapshot = fixture[["volume_quote"]]
    returns = fixture.dropna(subset=["turnover", "nav"])[["turnover", "nav"]]

    frame = analysis.capacity_frame(snapshot, returns)
    metrics = analysis.capacity_metrics(frame)

    assert metrics["adjustment_days"] == 23
    assert metrics["breach_days"] == 4
    assert metrics["maximum_participation"] == pytest.approx(0.002071095767825777)
    assert metrics["minimum_supported_initial_capital_usd"] == pytest.approx(
        482836.1949915012
    )

    future_changed = snapshot.copy()
    future_changed.loc[future_changed.index[-10]:, "volume_quote"] *= 1000.0
    changed = analysis.capacity_frame(future_changed, returns)
    first_oos = returns.index[0]
    pd.testing.assert_series_equal(
        frame.loc[:first_oos, "prior_median_quote_volume"],
        changed.loc[:first_oos, "prior_median_quote_volume"],
    )


def test_committed_result_discloses_the_single_rejected_candidate() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    assert result["candidate_accounting"] == {"passed": 0, "rejected": 1, "searched": 1}
    assert result["verdict"] == "rejected"
    assert result["live_eligible"] is False
    assert result["capacity_candidate"]["label"] == "initial-capital-usd-1000000"
    assert result["capacity_candidate"]["passes"] is False
    assert result["method"]["baseline_exchange_fee_bps_one_way"] == 5.0
    assert result["method"]["all_in_cost_sensitivities_bps"] == [5.0, 7.5, 10.0, 15.0]
    assert result["method"]["sealed_market_data_used"] is False


def test_exact_capacity_and_5bps_metrics_are_locked() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    btc = result["capacity_candidate"]["markets"]["BTC-USDT"]
    eth = result["capacity_candidate"]["markets"]["ETH-USDT"]

    assert btc["adjustment_days"] == 1316
    assert btc["breach_days"] == 133
    assert btc["maximum_participation"] == pytest.approx(0.007773581895252848)
    assert btc["minimum_supported_initial_capital_usd"] == pytest.approx(128640.82651662518)
    assert eth["adjustment_days"] == 1416
    assert eth["breach_days"] == 307
    assert eth["maximum_participation"] == pytest.approx(0.008893630850965593)
    assert eth["minimum_supported_initial_capital_usd"] == pytest.approx(112440.01654188613)

    btc_metrics = result["canonical_5bps_metrics"]["BTC-USDT"]
    eth_metrics = result["canonical_5bps_metrics"]["ETH-USDT"]
    assert btc_metrics["total_return"] == pytest.approx(1.4209166759944099)
    assert btc_metrics["sharpe"] == pytest.approx(0.7067199135624018)
    assert btc_metrics["profitable_folds"] == 12
    assert eth_metrics["total_return"] == pytest.approx(1.1057078943260912)
    assert eth_metrics["sharpe"] == pytest.approx(0.5794669646974043)
    assert eth_metrics["profitable_folds"] == 17
    assert result["live_gates"]["capacity"] == "fail"
    assert result["live_gates"]["overall_live_eligibility"] == "false"
