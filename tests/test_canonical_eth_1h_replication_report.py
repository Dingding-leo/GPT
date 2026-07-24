from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_ANALYSIS_PATH = (
    _REPOSITORY_ROOT
    / "reports"
    / "research"
    / "canonical-eth-1h-replication"
    / "analysis.py"
)
_RESULT_PATH = _ANALYSIS_PATH.with_name("result.json")


def _load_analysis() -> ModuleType:
    spec = importlib.util.spec_from_file_location("canonical_eth_1h_replication", _ANALYSIS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load ETH-USDT 1h replication analysis")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_committed_eth_replication_result_discloses_rejection_and_all_candidates() -> None:
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert result["candidate_accounting"] == {
        "architecture_candidates_passed": 0,
        "architecture_candidates_rejected": 1,
        "architecture_candidates_searched": 1,
        "candidate_evaluations": 324,
        "fold_local_internal_candidates": 27,
        "oos_folds": 12,
    }
    assert result["metrics_5bps"]["net_total_return"] == pytest.approx(
        0.21375686810673078
    )
    assert result["metrics_5bps"]["sharpe"] == pytest.approx(0.3945134663059659)
    assert result["metrics_5bps"]["annualized_turnover"] == pytest.approx(
        55.779778541287605
    )
    assert result["fold_stability"]["profitable_folds"] == 4
    assert result["month_stability"]["profitable_complete_months"] == 9
    assert result["year_stability"]["complete_years"] == 2
    assert result["activity"]["exposure_episode_count"] == 175
    assert result["activity"]["median_holding_hours"] == 5.0

    gates = result["gates"]
    assert gates["source_data_and_reselection_reproducible"] == "pass"
    assert gates["exact_5bps_profile_fidelity"] == "fail"
    assert result["cost_profile"]["executed"] == [1.0, 2.0]
    assert gates["benchmark_relative_risk_adjusted"] == "fail"
    assert gates["cross_market_replication"] == "fail"
    assert result["verdict"]["status"] == "rejected"
    assert result["verdict"]["live_eligible"] is False


def test_analysis_contract_matches_the_persisted_source_and_exact_cost_claim() -> None:
    module = _load_analysis()
    result = json.loads(_RESULT_PATH.read_text(encoding="utf-8"))

    assert module.CANONICAL_SIGNATURE == result["canonical_signature"]
    assert module.EXPECTED["artifact"] == result["source"]["artifact_sha256"]
    assert module.EXPECTED["returns"] == result["source"]["returns_sha256"]
    assert module.EXPECTED["report"] == result["source"]["report_sha256"]
    assert module.EXPECTED["snapshot"] == result["source"]["snapshot_sha256"]
    assert module.SOURCE_WORKFLOW_RUN_ID == result["source"]["workflow_run_id"]
    assert module.SOURCE_ARTIFACT_ID == result["source"]["artifact_id"]
    assert result["design"]["fee_bps_one_way"] == 5.0
    assert result["design"]["canonical_cost_scenarios_in_pnl"] == [5.0]
    assert result["design"]["separate_execution_diagnostics"] == [
        "maker_fill_quality",
        "no_fill",
        "partial_fill",
        "timeout",
        "adverse_selection",
        "latency",
    ]
