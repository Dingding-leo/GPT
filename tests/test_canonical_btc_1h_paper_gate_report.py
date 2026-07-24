from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_REPORT_DIR = _REPOSITORY_ROOT / "reports/research/canonical-btc-1h-paper-gate"
_REAL_OKX_FIXTURE = (
    _REPOSITORY_ROOT / "tests/fixtures/okx/btc_eth_oos_20200111_20200219/btc_usdt_returns.csv"
)
_REAL_OKX_FIXTURE_SHA256 = "417ff56ee3e71d8e2e8545ee4eb79091bd6f173bde29c79371aae96b65b12587"


def _load_analysis():
    path = _REPORT_DIR / "analysis.py"
    spec = importlib.util.spec_from_file_location("canonical_btc_1h_paper_gate", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_result_records_exact_5bps_rejection_and_complete_candidate_accounting() -> None:
    result = json.loads((_REPORT_DIR / "result.json").read_text(encoding="utf-8"))

    assert result["design"]["fee_bps_one_way"] == 5.0
    assert result["design"]["cost_scenarios_in_pnl"] == [5.0]
    assert result["candidate_accounting"] == {
        "architecture_candidates_passed": 0,
        "architecture_candidates_rejected": 1,
        "architecture_candidates_searched": 1,
        "fold_local_internal_candidates": 27,
        "oos_folds": 12,
    }
    assert result["metrics_5bps"]["net_total_return"] == 0.24349120050203132
    assert result["metrics_5bps"]["sharpe"] == 0.4515216668870213
    assert result["metrics_5bps"]["annualized_turnover"] == 52.95820465066092
    assert result["fold_stability"]["profitable_folds"] == 5
    assert result["month_stability"]["profitable_complete_months"] == 13
    assert result["month_stability"]["complete_months"] == 35
    assert result["year_stability"]["complete_years"] == 2
    assert result["verdict"] == {
        "live_eligible": False,
        "paper_testable": False,
        "reason": (
            "The 1h path is net profitable at 5 bps but lacks benchmark-relative edge, "
            "fold/month/year stability, ETH replication, capacity, maker execution, "
            "and prospective paper evidence."
        ),
        "status": "rejected",
    }


def test_metric_helpers_are_exercised_on_immutable_real_okx_returns() -> None:
    analysis = _load_analysis()
    observed_sha256 = hashlib.sha256(_REAL_OKX_FIXTURE.read_bytes()).hexdigest()
    assert observed_sha256 == _REAL_OKX_FIXTURE_SHA256

    frame = pd.read_csv(_REAL_OKX_FIXTURE)
    returns = pd.to_numeric(frame["strategy_return"], errors="raise")
    assert analysis._compound(returns) == 0.0
    assert analysis._expected_shortfall(returns) == 0.0


def test_blocked_execution_diagnostics_are_not_added_to_pnl() -> None:
    result = json.loads((_REPORT_DIR / "result.json").read_text(encoding="utf-8"))
    expected = {
        "maker_fill_quality",
        "no_fill",
        "partial_fill",
        "timeout",
        "adverse_selection",
        "latency",
    }
    assert set(result["design"]["separate_execution_diagnostics"]) == expected
    assert result["gates"]["maker_execution_diagnostics"]["status"] == "blocked"
    assert result["gates"]["prospective_paper_evidence"]["status"] == "blocked"
