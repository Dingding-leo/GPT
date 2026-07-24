from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

_REPORT_DIR = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "research"
    / "regime-pullback-recovery-1h"
)
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"
_RESULT_PATH = _REPORT_DIR / "result.json"
_FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "okx_btc_usdt_1h_pullback_recovery_20220125"
)


def _load_analysis():
    spec = importlib.util.spec_from_file_location(
        "regime_pullback_recovery_analysis",
        _ANALYSIS_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load pullback recovery analysis module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_committed_result_rejects_the_single_architecture_candidate() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {
        "architecture_candidates_passed": 0,
        "architecture_candidates_rejected": 1,
        "architecture_candidates_searched": 1,
        "bootstrap_resamples_per_market": 2000,
        "parameter_neighbourhood_paths": 4,
    }
    assert result["fixed_architecture"]["transaction_cost_bps_one_way"] == 5.0
    assert result["fixed_architecture"]["modeled_cost_paths"] == [
        "5bps_one_way_only"
    ]
    assert result["joint_retrospective_passes"] is False
    assert result["paper_testable"] is False
    assert result["live_eligible"] is False
    assert result["verdict"] == "rejected"

    expected = {
        "BTC-USDT": {
            "net_total_return": -0.057506565523855135,
            "sharpe": -0.04555065585021542,
            "annualized_turnover": 237.3992387284387,
            "profitable_folds": 6,
            "profitable_months": 16,
            "episodes_per_year": 123.01851851851852,
            "profit_factor": 0.9779239623078128,
            "maximum_supported_initial_capital_usd": 3529.5301353757122,
        },
        "ETH-USDT": {
            "net_total_return": -0.14387393731174325,
            "sharpe": -0.2092844222907815,
            "annualized_turnover": 168.92310702481953,
            "profitable_folds": 5,
            "profitable_months": 14,
            "episodes_per_year": 98.00925925925927,
            "profit_factor": 0.9337162243566259,
            "maximum_supported_initial_capital_usd": 2438.1709958153165,
        },
    }
    for market, expected_values in expected.items():
        details = result["markets"][market]
        assert details["metrics"]["net_total_return"] == pytest.approx(
            expected_values["net_total_return"], abs=1e-15
        )
        assert details["metrics"]["sharpe"] == pytest.approx(
            expected_values["sharpe"], abs=1e-15
        )
        assert details["metrics"]["annualized_turnover"] == pytest.approx(
            expected_values["annualized_turnover"], abs=1e-12
        )
        assert details["fold_stability"]["profitable_folds"] == expected_values[
            "profitable_folds"
        ]
        assert details["month_stability"][
            "profitable_complete_periods"
        ] == expected_values["profitable_months"]
        assert details["activity"]["episodes_per_year"] == pytest.approx(
            expected_values["episodes_per_year"], abs=1e-12
        )
        assert details["activity"][
            "completed_episode_profit_factor"
        ] == pytest.approx(expected_values["profit_factor"], abs=1e-15)
        assert details["capacity"][
            "maximum_supported_initial_capital_usd"
        ] == pytest.approx(
            expected_values["maximum_supported_initial_capital_usd"], abs=1e-9
        )
        assert details["tail_risk"]["passes"] is True
        assert details["retrospective_passes"] is False

    assert set(result["prospective_execution_diagnostics"].values()) == {
        "blocked_no_prospective_attempts"
    }


def test_real_okx_fixture_proves_delay_frozen_episode_and_exact_fee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    fixture_path = _FIXTURE_DIR / "candles.csv"

    assert _sha256(fixture_path) == metadata["fixture_sha256"]
    assert metadata["provider"] == "OKX"
    assert metadata["instrument"] == "BTC-USDT"
    assert metadata["timeframe"] == "1H"
    assert metadata["observations"] == 16

    snapshot = analysis.load_snapshot(fixture_path)
    monkeypatch.setattr(analysis, "REGIME_LOOKBACK", 3)
    monkeypatch.setattr(analysis, "ZSCORE_LOOKBACK", 3)
    monkeypatch.setattr(analysis, "VOLATILITY_LOOKBACK", 2)
    frame = analysis.build_pullback_frame(
        snapshot,
        entry_z=-0.5,
        exit_z=0.5,
        maximum_holding_hours=3,
    )

    first_signal = pd.Timestamp("2022-01-25T11:00:00Z")
    first_execution = pd.Timestamp("2022-01-25T12:00:00Z")
    first_exit = pd.Timestamp("2022-01-25T13:00:00Z")
    assert frame.loc[first_signal, "target_position"] == 1.0
    assert frame.loc[first_signal, "position"] == 0.0
    assert frame.loc[first_execution, "position"] == 1.0
    assert frame.loc[first_execution, "turnover"] == 1.0
    assert frame.loc[first_execution, "trading_cost"] == 0.0005
    assert frame.loc[first_exit, "position"] == 0.0
    assert frame.loc[first_exit, "turnover"] == 1.0
    assert frame.loc[first_exit, "trading_cost"] == 0.0005


def test_future_real_candle_mutation_cannot_change_prior_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    snapshot = analysis.load_snapshot(_FIXTURE_DIR / "candles.csv")
    monkeypatch.setattr(analysis, "REGIME_LOOKBACK", 3)
    monkeypatch.setattr(analysis, "ZSCORE_LOOKBACK", 3)
    monkeypatch.setattr(analysis, "VOLATILITY_LOOKBACK", 2)
    baseline = analysis.build_pullback_frame(
        snapshot,
        entry_z=-0.5,
        exit_z=0.5,
        maximum_holding_hours=3,
    )

    mutation_time = pd.Timestamp("2022-01-25T22:00:00Z")
    mutated = snapshot.copy()
    for column in ("open", "high", "low", "close"):
        mutated.loc[mutation_time, column] *= 1.25
    changed = analysis.build_pullback_frame(
        mutated,
        entry_z=-0.5,
        exit_z=0.5,
        maximum_holding_hours=3,
    )

    prior_end = mutation_time - pd.Timedelta(hours=1)
    columns = [
        "target_position",
        "position",
        "turnover",
        "gross_strategy_return",
        "trading_cost",
        "strategy_return",
    ]
    pd.testing.assert_frame_equal(
        baseline.loc[:prior_end, columns],
        changed.loc[:prior_end, columns],
        check_exact=True,
    )
    assert baseline.loc[mutation_time, "asset_return"] != changed.loc[
        mutation_time, "asset_return"
    ]
