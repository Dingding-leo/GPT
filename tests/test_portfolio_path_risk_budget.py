from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from gpt_quant.portfolio_path_risk_budget import (
    evaluate_portfolio_path_risk_budget,
    write_portfolio_path_risk_budget_report,
)
from gpt_quant.portfolio_underlying_risk import build_underlying_sleeve_risk

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "okx" / "btc_eth_full_path_20200111_20200219"


def _underlying_result():
    metadata = json.loads((_FIXTURE_DIR / "metadata.json").read_text(encoding="utf-8"))
    paths = {
        name: _FIXTURE_DIR / details["fixture_file"]
        for name, details in metadata["instruments"].items()
    }
    hashes = {name: details["fixture_sha256"] for name, details in metadata["instruments"].items()}
    provenance = {
        key: metadata[key]
        for key in (
            "provider",
            "market_type",
            "timeframe",
            "source_workflow_run_id",
            "source_artifact_id",
            "source_artifact_name",
            "source_artifact_sha256",
            "source_head_sha",
        )
    }
    provenance["return_file_sha256"] = hashes
    return build_underlying_sleeve_risk(
        paths,
        expected_sha256=hashes,
        initial_weights={"BTC-USDT": 0.5, "ETH-USDT": 0.5},
        provenance=provenance,
    )


def test_real_okx_path_budget_recomputes_tail_drawdown_turnover_and_cost_boundary(
    tmp_path: Path,
) -> None:
    underlying = _underlying_result()
    result = evaluate_portfolio_path_risk_budget(
        underlying,
        max_annualized_net_volatility=0.50,
        maximum_drawdown_floor=-0.40,
        max_annualized_weighted_underlying_turnover=25.0,
    )

    net_return = underlying.frame["portfolio_net_return"]
    annualized_volatility = float(net_return.std(ddof=1) * math.sqrt(365))
    annualized_turnover = float(
        underlying.frame["portfolio_weighted_underlying_turnover"].mean() * 365
    )
    nav = (1.0 + net_return).cumprod()
    running_peak = pd.Series(
        np.maximum.accumulate(np.concatenate(([1.0], nav.to_numpy())))[1:],
        index=nav.index,
    )
    drawdown = nav / running_peak - 1.0
    tail_observations = max(1, math.ceil(len(net_return) * 0.05))
    sorted_returns = np.sort(net_return.to_numpy(), kind="stable")

    assert result.metrics["annualized_net_volatility"] == pytest.approx(annualized_volatility)
    assert result.metrics["annualized_weighted_underlying_turnover"] == pytest.approx(
        annualized_turnover
    )
    assert result.metrics["maximum_drawdown"] == pytest.approx(float(drawdown.min()))
    assert result.metrics["current_drawdown"] == pytest.approx(float(drawdown.iloc[-1]))
    assert result.metrics["historical_expected_shortfall_95"] == pytest.approx(
        float(sorted_returns[:tail_observations].mean())
    )
    assert result.metrics["expected_shortfall_tail_observations"] == tail_observations
    assert result.metrics["worst_day_net_return"] == pytest.approx(float(net_return.min()))
    assert result.metrics["longest_underwater_duration_observations"] > 0
    assert result.payload["risk_budget"]["turnover_budget_passes"] is True
    assert result.passes is True
    assert result.payload["deployment_eligible"] is False
    assert result.payload["cost_attribution"]["exchange_fee"]["one_way_bps"] == 5.0
    assert result.payload["cost_attribution"]["spread"] == {"status": "not_modeled"}
    assert result.payload["cost_attribution"]["slippage"] == {"status": "not_modeled"}
    assert result.payload["cost_attribution"]["market_impact"] == {"status": "not_modeled"}
    assert result.payload["cost_attribution"]["latency"] == {"status": "not_modeled"}
    assert result.payload["cost_attribution"]["all_in_fixed_path_sensitivity_bps"] == [
        7.5,
        10.0,
        15.0,
    ]

    report = write_portfolio_path_risk_budget_report(result, tmp_path)
    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert persisted == result.to_dict()


def test_path_budget_rejects_tight_limits_and_refuses_mutated_evidence(
    tmp_path: Path,
) -> None:
    underlying = _underlying_result()
    measured = evaluate_portfolio_path_risk_budget(
        underlying,
        max_annualized_net_volatility=5.0,
        maximum_drawdown_floor=-0.99,
        max_annualized_weighted_underlying_turnover=100.0,
    )
    rejected = evaluate_portfolio_path_risk_budget(
        underlying,
        max_annualized_net_volatility=measured.metrics["annualized_net_volatility"] / 2.0,
        maximum_drawdown_floor=measured.metrics["maximum_drawdown"] / 2.0,
        max_annualized_weighted_underlying_turnover=(
            measured.metrics["annualized_weighted_underlying_turnover"] / 2.0
        ),
    )

    assert rejected.passes is False
    assert rejected.payload["risk_budget"]["volatility_budget_passes"] is False
    assert rejected.payload["risk_budget"]["drawdown_budget_passes"] is False
    assert rejected.payload["risk_budget"]["turnover_budget_passes"] is False
    assert len(rejected.payload["risk_budget"]["failure_reasons"]) == 3

    rejected.payload["metrics"]["maximum_drawdown"] = 0.0
    with pytest.raises(
        ValueError,
        match="portfolio path risk budget does not match verified underlying inputs",
    ):
        write_portfolio_path_risk_budget_report(rejected, tmp_path)
    assert not (tmp_path / "portfolio_path_risk_budget.json").exists()


def test_hourly_workflow_enforces_explicit_underlying_path_budgets() -> None:
    workflow = (
        Path(__file__).parents[1] / ".github" / "workflows" / "hourly-research.yml"
    ).read_text(encoding="utf-8")
    start = workflow.index("- name: Generate verified underlying sleeve risk report")
    end = workflow.index("- name: Generate verified portfolio risk report")
    block = workflow[start:end]

    assert 'MAX_ANNUALIZED_NET_VOLATILITY: "0.50"' in workflow
    assert 'MAXIMUM_DRAWDOWN_FLOOR: "-0.40"' in workflow
    assert 'MAX_ANNUALIZED_WEIGHTED_UNDERLYING_TURNOVER: "25.0"' in workflow
    assert '--max-annualized-net-volatility "$MAX_ANNUALIZED_NET_VOLATILITY"' in block
    assert '--maximum-drawdown-floor "$MAXIMUM_DRAWDOWN_FLOOR"' in block
    assert (
        "--max-annualized-weighted-underlying-turnover "
        '"$MAX_ANNUALIZED_WEIGHTED_UNDERLYING_TURNOVER"'
    ) in block
    assert "--fail-on-reject" in block
    assert "portfolio_path_risk_budget.json" not in workflow
    assert (
        "if: ${{ success() && hashFiles('reports/portfolio/portfolio_risk.json') != '' }}"
        in workflow
    )
