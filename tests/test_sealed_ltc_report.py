from __future__ import annotations

import json
from pathlib import Path


RESULT_PATH = (
    Path(__file__).resolve().parents[1]
    / "reports"
    / "research"
    / "sealed-ltc-validation"
    / "result.json"
)


def test_sealed_ltc_result_preserves_predeclared_rejection() -> None:
    result = json.loads(RESULT_PATH.read_text(encoding="utf-8"))

    assert result["protocol_commit"] == "7b9a8128539c10cc302f80602efd9f3973850592"
    assert result["frozen_base_commit"] == "29c28c1031bddda6c5e42f2672aaa6adaa004cad"
    assert result["data"]["provider"] == "OKX"
    assert result["data"]["instrument_id"] == "LTC-USDT"
    assert result["data"]["bar"] == "1Dutc"
    assert result["data"]["pagination_complete"] is True
    assert result["data"]["missing_intervals"] == 0
    assert result["data"]["duplicates_removed"] == 0
    assert len(result["data"]["normalized_csv_sha256"]) == 64
    assert len(result["data"]["raw_pages_sha256"]) == 64
    assert len(result["data"]["walk_forward_returns_sha256"]) == 64

    search = result["search"]
    assert search["candidates_per_fold"] == 27
    assert search["fold_count"] == 18
    assert search["candidate_evaluations"] == 486
    assert search["candidate_evaluations"] == search["candidates_per_fold"] * search["fold_count"]

    walk_forward = result["walk_forward"]
    assert walk_forward["aggregate_metrics"]["total_return"] < 0.0
    assert walk_forward["aggregate_metrics"]["sharpe"] < 0.0
    assert walk_forward["robustness_status"].startswith("reject:")

    drawdown = result["bootstrap"]["volatility_targeted_long"]["max_drawdown"]
    assert drawdown["ci_lower"] > 0.0
    assert drawdown["lower_bound_positive"] is True

    acceptance = result["acceptance"]
    assert acceptance["condition_1_repository_nonreject"] is False
    assert acceptance["condition_2_vol_target_mdd_ci_lower_positive"] is True
    assert acceptance["joint_verdict"] == "rejected"
