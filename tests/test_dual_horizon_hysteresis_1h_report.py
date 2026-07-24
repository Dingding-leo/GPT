from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_ANALYSIS_PATH = _ROOT / "reports" / "research" / "dual-horizon-hysteresis-1h" / "analysis.py"
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")
_FIXTURE_DIR = (
    _ROOT / "tests" / "fixtures" / "okx_btc_usdt_1h_dual_horizon_hysteresis_20220125_20220125"
)


def _load_analysis():
    spec = importlib.util.spec_from_file_location(
        "dual_horizon_hysteresis_analysis",
        _ANALYSIS_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_fixture() -> pd.DataFrame:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    fixture_path = _FIXTURE_DIR / "candles.csv"
    assert metadata["provider"] == "OKX"
    assert metadata["instrument"] == "BTC-USDT"
    assert metadata["bar"] == "1H"
    assert metadata["usage"] == "mechanics-only regression; no performance claim"
    assert _sha256(fixture_path) == metadata["fixture_sha256"]
    frame = pd.read_csv(fixture_path)
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
    return frame


def test_dual_horizon_is_causal_one_bar_delayed_and_exactly_five_bps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    monkeypatch.setattr(analysis, "VOLATILITY_LOOKBACK", 3)
    fixture = _load_fixture()

    frame = analysis.build_dual_horizon_frame(fixture, fast_lookback=2, slow_lookback=4)
    pd.testing.assert_series_equal(
        frame["position"],
        frame["target_position"].shift(1).fillna(0.0).rename("position"),
    )
    expected_turnover = frame["position"].diff().abs().fillna(frame["position"].abs())
    expected_cost = expected_turnover * 5.0 / 10_000.0
    np.testing.assert_allclose(frame["turnover"], expected_turnover, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(frame["trading_cost"], expected_cost, rtol=0.0, atol=0.0)
    np.testing.assert_allclose(
        frame["strategy_return"],
        frame["position"] * frame["asset_return"] - expected_cost,
        rtol=0.0,
        atol=1e-15,
    )
    assert (frame["position"] > 0.0).any()


def test_mixed_signal_hysteresis_and_future_invariance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _load_analysis()
    monkeypatch.setattr(analysis, "VOLATILITY_LOOKBACK", 3)
    fixture = _load_fixture()
    baseline = analysis.build_dual_horizon_frame(fixture, fast_lookback=2, slow_lookback=4)

    close = fixture["close"]
    fast = close.pct_change(2)
    slow = close.pct_change(4)
    mixed = (fast * slow < 0.0) & fast.notna() & slow.notna()
    mixed_indices = list(fixture.index[mixed])
    assert mixed_indices
    for timestamp in mixed_indices:
        prior = fixture.index.get_loc(timestamp) - 1
        if prior >= 0:
            previous_target_active = baseline["target_position"].iloc[prior] > 0.0
            current_target_active = baseline.at[timestamp, "target_position"] > 0.0
            assert current_target_active == previous_target_active

    mutated = fixture.copy()
    mutated.iloc[-1, mutated.columns.get_loc("close")] *= 1.25
    changed = analysis.build_dual_horizon_frame(mutated, fast_lookback=2, slow_lookback=4)
    pd.testing.assert_series_equal(
        baseline["target_position"].iloc[:-1],
        changed["target_position"].iloc[:-1],
    )


def test_committed_result_locks_candidate_accounting_and_rejection() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
    assert result["candidate_accounting"] == {
        "architecture_candidates_passed": 0,
        "architecture_candidates_rejected": 1,
        "architecture_candidates_searched": 1,
        "bootstrap_resamples_per_market": 2000,
        "parameter_neighbourhood_paths": 4,
    }
    assert result["fixed_architecture"]["transaction_cost_bps_one_way"] == 5.0
    assert result["fixed_architecture"]["modeled_cost_paths"] == ["5bps_one_way_only"]
    assert result["markets"]["BTC-USDT"]["metrics"]["sharpe"] == pytest.approx(1.075791531062742)
    assert result["markets"]["ETH-USDT"]["metrics"]["sharpe"] == pytest.approx(1.1782020542655411)
    assert result["joint_retrospective_passes"] is False
    assert result["paper_testable"] is False
    assert result["live_eligible"] is False
    assert result["verdict"] == "rejected"
