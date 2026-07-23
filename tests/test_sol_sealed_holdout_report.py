from __future__ import annotations

import json
from pathlib import Path

import pytest

_RESULT_PATH = (
    Path(__file__).parents[1] / "reports" / "research" / "sol-sealed-holdout" / "result.json"
)
_EXPECTED_SIGNATURE = (
    "canonical-5bps-sol-sealed-holdout-v1|market=SOL-USDT|"
    "architecture-base=9ab1bafddcc67ac78d4c42cd1bfb9e6e96b97449|"
    "source=public-OKX-spot-1Dutc|data-cutoff=2026-07-22T00:00:00Z|"
    "baseline=full-reselection-5bps|grid=27-declared-candidates|"
    "selection=730|test=90-nonoverlapping|execution=one-bar-delay|"
    "costs=5,7.5,10,15bps-fixed-selected-path|"
    "benchmark=volatility-targeted-long|"
    "benchmark-evidence=paired-noncircular-moving-block-bootstrap-"
    "sharpe-and-calmar-lower-bounds-positive|"
    "block=20|resamples=2000|confidence=0.95|seed=2026072405|"
    "fold-stability=repository-gate|"
    "year-stability=at-least-4-complete-years-and-60pct-profitable-"
    "and-worst-year-above-minus20pct|"
    "turnover=max20-and-15bps-total-return-and-sharpe-positive|"
    "neighbourhood=all-perturbations-positive-return-and-sharpe-and-dd-above-minus40pct|"
    "tail=maxdd-better-than-benchmark-and-above-minus35pct-and-es-better|"
    "candidate-count=1|no-same-market-retuning=true"
)


def _result() -> dict[str, object]:
    return json.loads(_RESULT_PATH.read_text(encoding="utf-8"))


def test_sol_holdout_is_one_frozen_rejected_candidate() -> None:
    result = _result()

    assert result["canonical_signature"] == _EXPECTED_SIGNATURE
    assert result["verdict"] == "rejected"
    assert result["candidate_accounting"] == {"searched": 1, "passed": 0, "rejected": 1}
    assert result["overall_live_eligible"] is False
    assert result["freeze"] == {
        "architecture_base_sha": "9ab1bafddcc67ac78d4c42cd1bfb9e6e96b97449",
        "data_cutoff_utc": "2026-07-22T00:00:00Z",
        "no_same_market_retuning": True,
        "pre_result_branch_head_sha": "5b622a5051f288abe3f294bcbc1206a4c568ceb4",
    }


def test_sol_exact_5bps_metrics_and_cost_stress_are_persisted() -> None:
    result = _result()
    metrics = result["metrics_5bps"]

    assert metrics["net_total_return"] == pytest.approx(1.6248271817610123)
    assert metrics["cagr"] == pytest.approx(0.29811274977245006)
    assert metrics["sharpe"] == pytest.approx(1.1589591577042695)
    assert metrics["sortino"] == pytest.approx(2.061615824994766)
    assert metrics["calmar"] == pytest.approx(1.315328250641238)
    assert metrics["max_drawdown"] == pytest.approx(-0.22664513563600308)
    assert metrics["annualized_turnover"] == pytest.approx(10.90476828445051)
    assert result["cost_stress"]["15 bps"]["total_return"] == pytest.approx(
        1.521207220187534
    )
    assert result["cost_stress"]["15 bps"]["sharpe"] == pytest.approx(
        1.1158688243247084
    )


def test_sol_fails_predeclared_statistical_and_stability_gates() -> None:
    result = _result()
    gates = result["gates"]
    bootstrap = result["benchmark_bootstrap"]
    folds = result["fold_stability"]

    assert bootstrap["sharpe"]["ci_lower"] == pytest.approx(-0.46869487584786335)
    assert bootstrap["calmar"]["ci_lower"] == pytest.approx(-1.0465936089056846)
    assert folds["profitable_folds"] == 8
    assert folds["fold_count"] == 15
    assert folds["max_positive_fold_share"] == pytest.approx(0.669996162967344)
    assert gates["benchmark_relative_risk_adjusted"] == "fail"
    assert gates["fold_stability"] == "fail"
    assert gates["year_stability"] == "fail"
    assert gates["untouched_market_validation"] == "fail"
    assert gates["turnover_and_cost_viability"] == "pass"
    assert gates["parameter_neighborhood_stability"] == "pass"
    assert gates["tail_risk"] == "pass"


def test_sol_result_preserves_real_data_and_workflow_provenance() -> None:
    result = _result()
    provenance = result["provenance"]
    validation = result["validation"]

    assert provenance["market"] == "SOL-USDT"
    assert provenance["provider"] == "OKX"
    assert provenance["timeframe"] == "1Dutc"
    assert provenance["observations"] == 1350
    assert provenance["returns_sha256"] == (
        "01121d2c583c4280ef585ceee42b80da873f9437fd609271e346f7ce8973b5bf"
    )
    assert provenance["snapshot_sha256"] == (
        "d1d27fc2147897d58701aa36afcff1f1509124b8f6546822b4a455e053841d8e"
    )
    assert validation["workflow_run_id"] == 30040059930
    assert validation["artifact_id"] == 8576864761
    assert validation["artifact_sha256"] == (
        "3485ddf8c3a2c608fcfeaecf340580c2c61883944459ddd46117b760885dba09"
    )
