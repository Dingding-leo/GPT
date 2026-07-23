from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

_REPORT_DIR = Path("reports/research/canonical-5bps-execution-delay-cost-stress")
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"
_RESULT_PATH = _REPORT_DIR / "result.json"
_FIXTURE_DIR = Path("tests/fixtures/okx_btc_usdt_5bps_delay_20200111_20200219")


def _load_analysis() -> ModuleType:
    spec = importlib.util.spec_from_file_location("canonical_delay_analysis", _ANALYSIS_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_okx_fixture_provenance_and_delay_accounting() -> None:
    analysis = _load_analysis()
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    fixture_path = _FIXTURE_DIR / "returns.csv"
    frame = pd.read_csv(fixture_path)

    assert metadata["provider"] == "OKX"
    assert metadata["instrument"] == "BTC-USDT"
    assert metadata["timeframe"] == "1Dutc"
    assert metadata["source_artifact_id"] == 8566608828
    assert metadata["fixture_sha256"] == _sha256(fixture_path)
    assert len(frame) == metadata["rows"] == 40

    delayed = analysis.build_delayed_returns(
        frame,
        total_delay_bars=3,
        all_in_cost_bps=15.0,
    )
    expected_position = frame["position"].shift(2).fillna(0.0)
    expected_turnover = expected_position.diff().abs()
    expected_turnover.iloc[0] = abs(expected_position.iloc[0])
    expected_gross = expected_position * frame["asset_return"]
    expected_cost = expected_turnover * 0.0015

    assert delayed["delayed_position"].to_numpy() == pytest.approx(expected_position.to_numpy())
    assert delayed["turnover"].to_numpy() == pytest.approx(expected_turnover.to_numpy())
    assert delayed["gross_return"].to_numpy() == pytest.approx(expected_gross.to_numpy())
    assert delayed["cost"].to_numpy() == pytest.approx(expected_cost.to_numpy())
    assert delayed["net_return"].to_numpy() == pytest.approx(
        (expected_gross - expected_cost).to_numpy()
    )


def test_paired_moving_block_bootstrap_is_deterministic() -> None:
    analysis = _load_analysis()
    frame = pd.read_csv(_FIXTURE_DIR / "returns.csv")
    scenario_returns = {}
    for total_delay in (1, 2, 3):
        scenario = analysis.build_delayed_returns(
            frame,
            total_delay_bars=total_delay,
            all_in_cost_bps=5.0,
        )
        scenario_returns[f"delay_{total_delay}"] = scenario["net_return"].to_numpy()

    first = analysis.bootstrap_intervals(scenario_returns, seed=2026072401)
    second = analysis.bootstrap_intervals(scenario_returns, seed=2026072401)

    assert first == second
    assert set(first) == {"delay_1", "delay_2", "delay_3"}
    for scenario in first.values():
        assert len(scenario["annualized_arithmetic_mean"]) == 2
        assert len(scenario["sharpe"]) == 2
        assert np.isfinite(scenario["annualized_arithmetic_mean"]).all()
        assert np.isfinite(scenario["sharpe"]).all()


def test_result_records_one_rejected_candidate_and_all_stresses() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["canonical_signature"].endswith("candidate_count=1")
    assert result["candidate_accounting"] == {
        "live_critical_scenarios_per_market": 8,
        "passed": 0,
        "rejected": 1,
        "strategy_candidates_searched": 1,
        "stress_scenarios_per_market": 8,
    }
    assert result["verdict"] == "rejected"
    assert result["execution_delay_gate_passes"] is False
    assert result["live_gate_status"]["live_eligible"] is False
    assert result["method"]["all_in_costs_bps"] == [5.0, 7.5, 10.0, 15.0]
    assert result["method"]["live_critical_total_delay_bars"] == [2, 3]

    for market in ("BTC-USDT", "ETH-USDT"):
        market_result = result["markets"][market]
        assert market_result["baseline_5bps"]["total_return"] > 0.0
        assert market_result["baseline_5bps"]["sharpe"] > 0.0
        assert len(market_result["stress_scenarios"]) == 8
        assert market_result["failed_scenarios"]


def test_validation_rejects_timezone_naive_rows() -> None:
    analysis = _load_analysis()
    frame = pd.read_csv(_FIXTURE_DIR / "returns.csv")
    frame.loc[0, "timestamp"] = str(frame.loc[0, "timestamp"]).replace("+00:00", "")

    with pytest.raises(ValueError, match="explicit timezone"):
        analysis.build_delayed_returns(
            frame,
            total_delay_bars=2,
            all_in_cost_bps=5.0,
        )
