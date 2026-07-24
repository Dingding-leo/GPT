from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

_ROOT = Path(__file__).resolve().parent
_ANALYSIS_PATH = _ROOT / "analysis.py"
_RESULT_PATH = _ROOT / "result.json"
_FIXTURE_DIR = _ROOT / "fixture"


def _load_analysis():
    spec = importlib.util.spec_from_file_location(
        "cross_sectional_leader_rotation_1h", _ANALYSIS_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_source() -> pd.DataFrame:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    csv_path = _FIXTURE_DIR / "returns.csv"
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == metadata["fixture_sha256"]
    frame = pd.read_csv(csv_path)
    timestamps = pd.DatetimeIndex(pd.to_datetime(frame.pop("timestamp"), utc=True))
    frame.index = timestamps
    frame.index.name = "timestamp"
    return frame


def test_persisted_rejection_uses_exact_five_bps_only() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
    assert result["candidate_accounting"] == {
        "architecture_candidates_searched": 1,
        "neighbourhood_paths": 4,
        "passed": 0,
        "rejected": 1,
    }
    assert result["architecture"]["transaction_cost_bps_one_way"] == 5.0
    assert result["architecture"]["additional_costs_in_pnl"] == []
    assert result["verdict"] == "rejected"
    assert result["gates"]["paper_testable"] is False
    assert result["gates"]["live_eligible"] is False
    assert result["strategy_metrics"]["total_return"] == 0.5122146442808071
    assert result["fold_stability"]["profitable_folds"] == 6
    assert result["calendar_stability"]["profitable_complete_months"] == 10


def test_real_okx_fixture_preserves_one_bar_delay_and_fee_identity() -> None:
    analysis = _load_analysis()
    source = _fixture_source()
    spec = analysis.ArchitectureSpec(
        momentum_lookback=24,
        regime_lookback=48,
        volatility_lookback=24,
        decision_cadence_hours=6,
    )
    path = analysis.build_architecture(source, spec)
    np.testing.assert_allclose(
        path["btc_position"].iloc[1:].to_numpy(),
        path["btc_target_position"].iloc[:-1].to_numpy(),
        atol=0.0,
        rtol=0.0,
    )
    np.testing.assert_allclose(
        path["eth_position"].iloc[1:].to_numpy(),
        path["eth_target_position"].iloc[:-1].to_numpy(),
        atol=0.0,
        rtol=0.0,
    )
    np.testing.assert_allclose(
        path["exchange_fee"].to_numpy(),
        path["turnover"].to_numpy() * 0.0005,
        atol=1e-15,
        rtol=0.0,
    )
    np.testing.assert_allclose(
        path["net_return"].to_numpy(),
        path["gross_return"].to_numpy() - path["exchange_fee"].to_numpy(),
        atol=1e-15,
        rtol=0.0,
    )


def test_future_price_change_cannot_change_earlier_targets() -> None:
    analysis = _load_analysis()
    source = _fixture_source()
    spec = analysis.ArchitectureSpec(
        momentum_lookback=24,
        regime_lookback=48,
        volatility_lookback=24,
        decision_cadence_hours=6,
    )
    baseline = analysis.build_architecture(source, spec)
    changed = source.copy()
    changed.iloc[-1, changed.columns.get_loc("btc_close")] *= 1.25
    replay = analysis.build_architecture(changed, spec)
    columns = ["btc_target_position", "eth_target_position", "btc_position", "eth_position"]
    pd.testing.assert_frame_equal(baseline[columns].iloc[:-1], replay[columns].iloc[:-1])
