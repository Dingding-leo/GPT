from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parents[1]
_REPORT_DIR = _ROOT / "reports" / "research" / "canonical-5bps-live-gate"
_FIXTURE_DIR = _ROOT / "tests" / "fixtures" / "okx_btc_usdt_5bps_oos_20200111_20200219"


def _analysis_module():
    spec = importlib.util.spec_from_file_location(
        "canonical_5bps_live_gate", _REPORT_DIR / "analysis.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_okx_fixture_hash_and_metric_primitives() -> None:
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    payload = (_FIXTURE_DIR / "returns.csv").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == metadata["fixture_sha256"]
    assert metadata["provider"] == "OKX"
    assert metadata["source_artifact_id"] == 8566608828

    module = _analysis_module()
    frame = pd.read_csv(_FIXTURE_DIR / "returns.csv")
    validated = module.validate_frame(frame)
    assert len(validated) == 40
    assert module.total_return(validated["strategy_return"]) == pytest.approx(
        float((1.0 + validated["strategy_return"]).prod() - 1.0)
    )
    assert module.holding_episode_metrics(validated)["count"] >= 0


def test_calendar_metrics_are_version_independent_at_year_boundary() -> None:
    module = _analysis_module()
    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2021-12-30T00:00:00Z",
                    "2021-12-31T00:00:00Z",
                    "2022-01-01T00:00:00Z",
                    "2022-01-02T00:00:00Z",
                ],
                utc=True,
            ),
            "strategy_return": [0.10, -0.05, 0.02, 0.03],
        }
    )

    metrics = module.calendar_metrics(frame)

    assert metrics["month_count"] == 2
    assert metrics["profitable_months"] == 2
    assert metrics["losing_or_flat_months"] == 0
    assert metrics["completed_year_count"] == 0
    assert metrics["years"] == [
        {
            "year": 2021,
            "return": pytest.approx((1.10 * 0.95) - 1.0),
            "partial": True,
        },
        {
            "year": 2022,
            "return": pytest.approx((1.02 * 1.03) - 1.0),
            "partial": True,
        },
    ]


def test_committed_inventory_is_hash_bound_and_rejected() -> None:
    result = json.loads((_REPORT_DIR / "result.json").read_text(encoding="utf-8"))
    assert result["source"]["artifact_sha256"] == (
        "ab0846180ff5b9397de26de8ca8d728ad237be00bdb92ba1612ef6ba243fc149"
    )
    assert result["candidate_accounting"] == {
        "searched": 1,
        "passed": 0,
        "rejected": 1,
    }
    assert result["verdict"] == "rejected"
    assert result["live_eligible"] is False
    assert set(result["markets"]) == {"BTC-USDT", "ETH-USDT"}


def test_exact_5bps_metrics_and_cost_scenarios_are_persisted() -> None:
    result = json.loads((_REPORT_DIR / "result.json").read_text(encoding="utf-8"))
    btc = result["markets"]["BTC-USDT"]
    eth = result["markets"]["ETH-USDT"]
    assert btc["settings"]["strategy"]["transaction_cost_bps"] == 5.0
    assert eth["settings"]["strategy"]["transaction_cost_bps"] == 5.0
    assert set(btc["cost_scenarios_bps"]) == {"5", "7.5", "10", "15"}
    assert set(eth["cost_scenarios_bps"]) == {"5", "7.5", "10", "15"}
    assert btc["returns"]["net_total_return"] == pytest.approx(1.4209166759944099)
    assert eth["returns"]["net_total_return"] == pytest.approx(1.1057078943260912)
    assert btc["cost_scenarios_bps"]["15"]["total_return"] > 0.0
    assert eth["cost_scenarios_bps"]["15"]["total_return"] > 0.0


def test_live_gate_fails_closed_on_missing_deployment_evidence() -> None:
    result = json.loads((_REPORT_DIR / "result.json").read_text(encoding="utf-8"))
    gates = result["joint_gates"]
    assert gates["benchmark_relative_risk_adjusted"] == "fail"
    assert gates["fold_stability"] == "fail"
    assert gates["year_stability"] == "fail"
    for gate in (
        "separate_spread_slippage_impact_latency",
        "capacity",
        "execution_delay_robustness",
        "untouched_market_validation",
        "prospective_forward_validation",
    ):
        assert gates[gate] == "blocked"
