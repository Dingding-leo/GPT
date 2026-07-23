from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO_ROOT = Path(__file__).parents[1]
_REPORT_DIR = _REPO_ROOT / "reports" / "research" / "fold_local_top3_score_ensemble"
_RESULT_PATH = _REPORT_DIR / "result.json"
_PACKAGE_NAME = "fold_local_top3_score_ensemble"
_PACKAGE_SPEC = importlib.util.spec_from_file_location(
    _PACKAGE_NAME,
    _REPORT_DIR / "__init__.py",
    submodule_search_locations=[str(_REPORT_DIR)],
)
if _PACKAGE_SPEC is None or _PACKAGE_SPEC.loader is None:
    raise RuntimeError(f"unable to import research package from {_REPORT_DIR}")
_package = importlib.util.module_from_spec(_PACKAGE_SPEC)
sys.modules[_PACKAGE_NAME] = _package
_PACKAGE_SPEC.loader.exec_module(_package)
analysis = importlib.import_module(f"{_PACKAGE_NAME}.analysis")


def _result() -> dict[str, object]:
    return json.loads(_RESULT_PATH.read_text(encoding="utf-8"))


def test_candidate_definition_is_single_predeclared_top3_architecture() -> None:
    grid = analysis.candidate_grid()

    assert analysis.MARKETS == ("BTC-USDT", "ETH-USDT")
    assert "SOL-USDT" not in analysis.MARKETS
    assert analysis.TOP_K == 3
    assert analysis.BASELINE_COST_BPS == pytest.approx(5.0)
    assert analysis.ALL_IN_COSTS_BPS == (5.0, 7.5, 10.0, 15.0)
    assert analysis.NEIGHBOUR_TOP_K == (2, 4)
    assert len(grid) == 27
    assert len(set(grid)) == 27
    assert grid[0] == (30, 2, 0.55)
    assert grid[-1] == (180, 10, 0.85)


def test_noncircular_block_indices_are_seeded_and_contiguous_within_blocks() -> None:
    first = analysis.noncircular_block_indices(40, 7, np.random.default_rng(2026072406))
    second = analysis.noncircular_block_indices(40, 7, np.random.default_rng(2026072406))

    assert np.array_equal(first, second)
    assert first.shape == (40,)
    assert np.all((0 <= first) & (first < 40))
    for start in range(0, 35, 7):
        block = first[start : start + 7]
        assert np.array_equal(np.diff(block), np.ones(len(block) - 1, dtype=int))


def test_persisted_result_rejects_architecture_and_preserves_exact_metrics() -> None:
    result = _result()

    assert result["canonical_signature"] == analysis.CANONICAL_SIGNATURE
    assert result["candidate_accounting"] == {
        "architecture_candidates_searched": 1,
        "cost_stresses_bps": [5.0, 7.5, 10.0, 15.0],
        "declared_grid_members_scored_per_fold": 27,
        "delay_stresses_total_bars": [2, 3],
        "neighbourhood_stresses": ["top_2", "top_4"],
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["architecture_freeze_eligible"] is False
    assert result["live_eligible"] is False
    assert result["joint_gates"]["development_benchmark_relative_risk_adjusted"] == "fail"
    assert result["joint_gates"]["fold_stability"] == "fail"
    assert result["joint_gates"]["execution_delay_robustness"] == "fail"

    btc = result["markets"]["BTC-USDT"]
    eth = result["markets"]["ETH-USDT"]
    assert btc["metrics_5bps"]["total_return"] == pytest.approx(1.239479958177661)
    assert btc["metrics_5bps"]["sharpe"] == pytest.approx(0.6548735577594222)
    assert btc["metrics_5bps"]["annualized_turnover"] == pytest.approx(14.321919517629233)
    assert btc["fold_stability"]["profitable_folds"] == 13
    assert btc["fold_stability"]["passes"] is False
    assert btc["fold_stability"]["max_positive_fold_share"] == pytest.approx(
        0.45659607753384496
    )

    assert eth["metrics_5bps"]["total_return"] == pytest.approx(1.6264537442482534)
    assert eth["metrics_5bps"]["sharpe"] == pytest.approx(0.7216293857158551)
    assert eth["metrics_5bps"]["annualized_turnover"] == pytest.approx(14.331492844793107)
    assert eth["fold_stability"]["profitable_folds"] == 17
    assert eth["fold_stability"]["passes"] is True
    assert eth["fold_stability"]["max_positive_fold_share"] == pytest.approx(
        0.2301373784969282
    )


def test_persisted_result_discloses_all_cost_neighbourhood_and_delay_scenarios() -> None:
    result = _result()

    for market in analysis.MARKETS:
        details = result["markets"][market]
        assert set(details["cost_scenarios_bps"]) == {"5", "7.5", "10", "15"}
        assert set(details["parameter_neighbourhood"]) == {"top_2", "top_4"}
        delay_summary = details["execution_delay_scenarios"]
        assert delay_summary["scenarios_tested"] == 8
        assert {record["scenario"] for record in delay_summary["scenario_results"]} == {
            f"delay_{delay}_bars_cost_{cost:g}_bps"
            for delay in (2, 3)
            for cost in (5.0, 7.5, 10.0, 15.0)
        }
        assert details["gates"]["turnover_and_5_7.5_10_15bps_viability"] == "pass"
        assert details["gates"]["parameter_neighbourhood_stability"] == "pass"
        assert details["gates"]["tail_risk"] == "pass"
