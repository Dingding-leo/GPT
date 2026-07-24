from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_REPORT_DIR = (
    Path(__file__).parents[1] / "reports" / "research" / "cross_market_maximin_shared_candidate"
)
_ANALYSIS_PATH = _REPORT_DIR / "analysis.py"
_RESULT_PATH = _REPORT_DIR / "result.json"
_SPEC = importlib.util.spec_from_file_location("cross_market_maximin_analysis", _ANALYSIS_PATH)
assert _SPEC is not None and _SPEC.loader is not None
analysis = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(analysis)


def test_shared_score_aggregation_is_fail_closed() -> None:
    scores = {"BTC-USDT": 0.2, "ETH-USDT": -0.1}
    assert analysis.aggregate_shared_scores(scores, "maximin") == pytest.approx(-0.1)
    assert analysis.aggregate_shared_scores(scores, "mean_score") == pytest.approx(0.05)

    with pytest.raises(ValueError, match="exactly the declared development markets"):
        analysis.aggregate_shared_scores({"BTC-USDT": 0.2}, "maximin")
    with pytest.raises(ValueError, match="unsupported shared-score rule"):
        analysis.aggregate_shared_scores(scores, "median")


def test_persisted_result_rejects_one_disclosed_architecture() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
    accounting = result["candidate_accounting"]
    assert accounting["architecture_candidates_searched"] == 1
    assert accounting["passed"] == 0
    assert accounting["rejected"] == 1
    assert accounting["neighbourhood_stresses"] == ["mean_score", "rank_sum"]
    assert result["verdict"] == "rejected"
    assert result["architecture_freeze_eligible"] is False
    assert result["live_eligible"] is False


def test_exact_5bps_metrics_and_gate_failures_are_persisted() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))
    expected = {
        "BTC-USDT": {
            "total_return": 0.7162602231334021,
            "sharpe": 0.47659480616372035,
            "profitable_folds": 11,
        },
        "ETH-USDT": {
            "total_return": 0.7446471929469303,
            "sharpe": 0.4603330788041208,
            "profitable_folds": 16,
        },
    }
    for market, values in expected.items():
        market_result = result["markets"][market]
        assert market_result["metrics_5bps"]["total_return"] == pytest.approx(
            values["total_return"]
        )
        assert market_result["metrics_5bps"]["sharpe"] == pytest.approx(values["sharpe"])
        assert market_result["fold_stability"]["profitable_folds"] == values["profitable_folds"]
        assert sum(market_result["fold_selection_summary"]["selection_frequency"].values()) == 27

    assert result["joint_gates"]["development_benchmark_relative_risk_adjusted"] == "fail"
    assert result["joint_gates"]["fold_stability"] == "fail"
    assert result["joint_gates"]["year_stability"] == "fail"
    assert result["joint_gates"]["execution_delay_robustness"] == "fail"
    assert result["joint_gates"]["turnover_and_5_7.5_10_15bps_viability"] == "pass"
    assert result["joint_gates"]["parameter_neighbourhood_stability"] == "pass"
    assert result["joint_gates"]["tail_risk"] == "pass"
